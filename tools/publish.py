#!/usr/bin/env python3
"""通过 GitHub REST API 发布本仓库。

**为什么不用 git push**：某些网络环境下 `github.com:443` 不可达，但 `api.github.com` 可达。
GitHub 的 Git Data API 允许只用 REST 完成「建仓库 → 上传全部文件 → 一次提交」：
    blobs（逐个文件）→ tree（含全部 blob）→ commit → ref

token 从环境变量 `GITHUB_TOKEN` / `GH_TOKEN` 读取，其次读 `~/.gh_token` 文件。
**不通过命令行参数传入**，避免 token 出现在进程列表与 shell 历史里。需要 `repo` 权限。

用法：
    python3 tools/publish.py --repo polytech-tree-harmonyos
    python3 tools/publish.py --repo myrepo --owner myname --private
"""
import argparse
import base64
import concurrent.futures
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = 'https://api.github.com'
UA = 'polytech-tree-harmonyos-publish'


def read_token() -> str:
    for key in ('GITHUB_TOKEN', 'GH_TOKEN'):
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()
    path = os.path.expanduser('~/.gh_token')
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as fh:
            token = fh.read().strip()
        if token:
            return token
    sys.exit('未找到 token。请设置环境变量 GITHUB_TOKEN，或把 token 写入 ~/.gh_token')


def api(method: str, path: str, token: str, payload=None):
    url = path if path.startswith('http') else API + path
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    req.add_header('User-Agent', UA)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'ignore')[:500]
        raise RuntimeError('%s %s -> HTTP %s\n%s' % (method, path, exc.code, detail)) from None


def branch_absent(exc: Exception) -> bool:
    """判断"分支/提交还不存在"。

    注意空仓库上取 ref 会返回 409（Git Repository is empty）而不是 404，
    两种都要认，否则在全新仓库上第一次发布会直接抛错。
    """
    text = str(exc)
    return 'HTTP 404' in text or 'HTTP 409' in text


def git_ls_files(root: str):
    """用 git ls-files 取待提交清单，这样 .gitignore 与已跟踪状态都会自动生效。"""
    out = subprocess.run(['git', 'ls-files'], cwd=root, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.split('\n') if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True, help='仓库名')
    ap.add_argument('--owner', default=None, help='默认取 token 所属用户')
    ap.add_argument('--branch', default='main')
    ap.add_argument('--private', action='store_true')
    ap.add_argument('--description',
                    default='人类科技树的鸿蒙应用 · Offline 3D tech tree in ArkWeb — HarmonyOS packaging of polytech-tree')
    ap.add_argument('--message', default=None, help='提交信息，默认取本地 HEAD 的提交信息')
    ap.add_argument('--root', default=None, help='仓库工作区（默认脚本所在仓库根）')
    args = ap.parse_args()

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    token = read_token()

    me = api('GET', '/user', token)
    owner = args.owner or me['login']
    print('身份      : %s' % me['login'])

    full = '%s/%s' % (owner, args.repo)
    try:
        repo = api('GET', '/repos/' + full, token)
        print('仓库      : 已存在 %s' % repo['html_url'])
    except RuntimeError as exc:
        if 'HTTP 404' not in str(exc):
            raise
        repo = api('POST', '/user/repos', token, {
            'name': args.repo,
            'private': args.private,
            'description': args.description,
            'auto_init': False,
        })
        print('仓库      : 已创建 %s' % repo['html_url'])

    # 空仓库上创建 blob 会被拒（409 "Git Repository is empty"）——
    # Git Data API 要求仓库里已经存在至少一个 commit。
    # 所以先用 Contents API 落一个 README，产生首个提交与分支。
    try:
        api('GET', '/repos/%s/git/ref/heads/%s' % (full, args.branch), token)
    except RuntimeError as exc:
        if not branch_absent(exc):
            raise
        readme = os.path.join(root, 'README.md')
        if os.path.isfile(readme):
            with open(readme, 'rb') as fh:
                seed = base64.b64encode(fh.read()).decode('ascii')
            api('PUT', '/repos/%s/contents/README.md' % full, token, {
                'message': 'chore: 初始化仓库（先落 README）',
                'content': seed,
                'branch': args.branch,
            })
            print('初始化    : 空仓库，已用 README 建立首个提交')

    files = git_ls_files(root)
    if not files:
        sys.exit('git ls-files 为空，先在仓库里 git add 吧')
    total_bytes = sum(os.path.getsize(os.path.join(root, f)) for f in files)
    print('待上传    : %d 个文件, %.1f MB' % (len(files), total_bytes / 1048576))

    def make_blob(rel: str):
        with open(os.path.join(root, rel), 'rb') as fh:
            content = base64.b64encode(fh.read()).decode('ascii')
        result = api('POST', '/repos/%s/git/blobs' % full, token,
                     {'content': content, 'encoding': 'base64'})
        return rel, result['sha']

    tree = []
    done = 0
    # 并发上传：180+ 个文件串行会慢到难以接受
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for rel, sha in pool.map(make_blob, files):
            mode = '100755' if os.access(os.path.join(root, rel), os.X_OK) else '100644'
            tree.append({'path': rel, 'mode': mode, 'type': 'blob', 'sha': sha})
            done += 1
            if done % 25 == 0 or done == len(files):
                print('  上传进度: %d/%d' % (done, len(files)), flush=True)

    tree_obj = api('POST', '/repos/%s/git/trees' % full, token, {'tree': tree})
    print('tree      : %s' % tree_obj['sha'][:12])

    parents = []
    try:
        ref = api('GET', '/repos/%s/git/ref/heads/%s' % (full, args.branch), token)
        parents = [ref['object']['sha']]
        print('父提交    : %s（在已有分支上追加提交）' % parents[0][:12])
    except RuntimeError as exc:
        if not branch_absent(exc):
            raise
        print('父提交    : 无（首次提交）')

    message = args.message
    if not message:
        message = subprocess.run(['git', 'log', '-1', '--pretty=%B'], cwd=root,
                                 capture_output=True, text=True).stdout.strip()
    if not message:
        message = 'Update from tools/publish.py'

    commit = api('POST', '/repos/%s/git/commits' % full, token,
                 {'message': message, 'tree': tree_obj['sha'], 'parents': parents})
    print('commit    : %s' % commit['sha'][:12])

    if parents:
        api('PATCH', '/repos/%s/git/refs/heads/%s' % (full, args.branch), token,
            {'sha': commit['sha'], 'force': False})
    else:
        api('POST', '/repos/%s/git/refs' % full, token,
            {'ref': 'refs/heads/' + args.branch, 'sha': commit['sha']})
        # 空仓库的首个分支不一定是 main，显式设为默认分支
        try:
            api('PATCH', '/repos/' + full, token, {'default_branch': args.branch})
        except RuntimeError:
            pass

    print('')
    print('完成：%s/tree/%s' % (repo['html_url'], args.branch))
    return 0


if __name__ == '__main__':
    sys.exit(main())

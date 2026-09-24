# -*- coding: utf-8 -*-
"""
原子写入：先写同目录临时文件，再 os.replace 换名。

为什么需要：`techs.json` 会被流水线多个步骤反复整体重写，而取证脚本/编辑器/另一个会话
可能同时在读它。`open(path,'w')` 会先把文件截成 0 字节再写，读者就有窗口看到空文件或半截
JSON（实测把 --deep 取证直接撞崩过一次）。同一台机器上 os.replace 是原子的，读者要么看到
旧版本、要么看到新版本，不会看到中间态。
"""
import io
import json
import os
import time


def write_atomic(path, text):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    # Windows 上刚写完的临时文件可能仍被索引/杀软占用，os.replace 会瞬时报 PermissionError
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def write_json(path, obj, indent=2, trailing_newline=True):
    return write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=indent) + ("\n" if trailing_newline else ""))

/*
 * Copyright (c) 2026 Huawei Device Co., Ltd.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BusinessError } from '@kit.BasicServicesKit';

const DOMAIN: number = 0x0000;
const TAG: string = 'HumanTechTree';

/** 探测站点是否真的跑起来了：入口脚本会把统计行填进 #statLine */
const PROBE_SCRIPT: string =
  '(() => {' +
  '  const el = document.getElementById("statLine");' +
  '  return el ? el.textContent : "(no #statLine)";' +
  '})()';

/**
 * 人类科技树
 *
 * ArkWeb 承载打包在 rawfile 里的三维科技树站点：3876 项科技按时代分层、
 * 按领域分扇区堆成一座可旋转的塔。站点是纯静态 ESM 应用（three.js + import map），
 * 数据随包发出，运行时不发起任何网络请求。
 */
@Entry
@Component
struct Index {
  private controller: webview.WebviewController = new webview.WebviewController();

  /**
   * 页面加载完成后回读 #statLine。
   * rawfile 下如果 ESM 因 MIME 或 import map 问题没跑起来，这里会读到空串或旧值，
   * 真机排查时用 hdc log 过滤 TAG 即可定位。
   */
  private probe(): void {
    this.controller.runJavaScript(PROBE_SCRIPT)
      .then((result: string) => {
        hilog.info(DOMAIN, TAG, 'probe statLine = %{public}s', result);
      })
      .catch((err: BusinessError) => {
        hilog.error(DOMAIN, TAG, 'probe failed: %{public}s', JSON.stringify(err));
      });
  }

  build() {
    Column() {
      Web({ src: $rawfile('index.html'), controller: this.controller })
        .javaScriptAccess(true)
        .domStorageAccess(true)
        .fileAccess(true)
        .imageAccess(true)
        .onlineImageAccess(false)
        .zoomAccess(false)
        .horizontalScrollBarAccess(false)
        .verticalScrollBarAccess(false)
        .darkMode(WebDarkMode.On)
        .forceDarkAccess(false)
        .backgroundColor('#05070F')
        .onPageEnd(() => {
          hilog.info(DOMAIN, TAG, 'page load end');
          this.probe();
        })
        .onConsole((event) => {
          hilog.info(DOMAIN, TAG, '[web] %{public}s', event.message.getMessage());
          return false;   // 不消费事件，继续交给系统默认处理
        })
        .onErrorReceive((event) => {
          hilog.error(DOMAIN, TAG, '[web error] %{public}s', event.error.getErrorInfo());
          return false;
        })
        .width('100%')
        .height('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#05070F')
  }
}

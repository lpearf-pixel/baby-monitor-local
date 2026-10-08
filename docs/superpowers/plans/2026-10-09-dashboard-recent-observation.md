# Dashboard 最近宝宝观察状态实施计划

- [x] Task 1：为状态枚举、时间字段、reason_code 和 30 秒过期合同补 RED/GREEN 测试。
- [x] Task 2：实现 0600 原子状态 writer/reader、worker generation、防止旧结果覆盖。
- [x] Task 3：接入 scheduler observer fan-out；失败/超时/迟到结果 fail closed，写入失败不阻断 Guardian。
- [x] Task 4：增加鉴权、no-store 的只读 API，并在运行时引用私有 status 文件。
- [x] Task 5：复用 Dashboard 唯一 15 秒刷新器，加入最近观察卡片和局部错误降级。
- [x] Task 6：运行视觉、Guardian、API、前端回归，更新交接文档；不部署、不启动家庭观察。

验收重点：无结果、过期、失败、超时、worker 重启和迟到响应不得显示为当前“没有宝宝”；
重复或更旧的输入帧不能刷新采集时间；诊断报告保持独立。

# P1 闸 A：本地 API、worker 与数据库实际输出

验证材料：`material_id = 6`，标题为“P1 本地验收样本”。它故意在**未配置云密钥**的环境中处理，用于验证 §7.2 所要求的诚实失败路径；它不是假造的 `ready` 材料。

## 创建材料

请求：`POST /materials`

```http
HTTP/1.1 202 Accepted
content-type: application/json

{"material_id":6,"job_id":6,"status":"pending"}
```

## Worker 实际输出

执行一次本地 worker 后，未发起云调用即在配置检查处失败：

```text
job=6 failed: DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。
```

## Job JSON 原文

请求：`GET /jobs/6`

```json
{"id":6,"kind":"tts","material_id":6,"status":"failed","payload":{"text":"雨の音を聞きながら、静かに本を読みます。明日も少しずつ進みましょう。"},"error_message":"DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。","attempts":1,"created_at":"2026-07-30T23:53:11.708462+08:00","updated_at":"2026-07-30T23:53:39.942973+08:00"}
```

## Material JSON 原文

请求：`GET /materials/6`

```json
{"id":6,"kind":"reading","title":"P1 本地验收样本","source_type":"paste","source_ref":null,"status":"failed","error_message":"DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。","duration_ms":null,"created_at":"2026-07-30T23:53:11.708462+08:00","updated_at":"2026-07-30T23:53:39.942973+08:00","segments":[],"audio_url":null}
```

## PostgreSQL 查询原文

```text
 id |  kind   |      title      | status | duration_ms |                              error_message
----+---------+-----------------+--------+-------------+-------------------------------------------------------------------------
  6 | reading | P1 本地验收样本 | failed |             | DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。
(1 row)

 idx | left | start_ms | end_ms
-----+------+----------+--------
(0 rows)

 kind | purpose | has_oss | has_local | bytes | duration_ms
------+---------+---------+-----------+-------+-------------
(0 rows)

 id | kind | status | attempts |                                  left
----+------+--------+----------+-------------------------------------------------------------------------
  6 | tts  | failed |        1 | DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。
(1 row)
```

本记录证明 material/job 状态、错误信息和失败后的无媒体资产状态均持久化到 PostgreSQL；不应将其用于证明云链路成功。

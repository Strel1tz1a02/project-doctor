# 隔离环境的本机入口

首次运行真实目标前构建：

```powershell
docker build -t project-doctor-ingress:latest demo/ingress
```

应用和数据库仅连接 `internal: true` 网络。入口容器同时连接内部网络和入口网络，将宿主机 `127.0.0.1:18080` 的 TCP 连接固定转发到 `app:8080`。客户端不能指定其他目的地址，入口以非 root 用户、只读文件系统和零额外 capability 运行。

此布局解决 Docker Desktop 29.2.0 在仅内部网络上不建立发布端口的问题。Java 17 转发器没有第三方库，构建和运行镜像按摘要固定；不依赖目标应用镜像。协议支持当前串行 HTTP 测试，连接空闲超时为 30 秒。

目标应用镜像仍需单独构建为 `project-doctor-target:latest`，并提供能够反映应用及种子数据已就绪的 HEALTHCHECK。结束任务时，平台会清理应用、数据库、入口和两个网络。

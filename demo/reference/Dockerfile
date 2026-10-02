# 参考形状：与 slow-query-demo 根目录 Dockerfile 保持一致。
# 构建目标镜像（仅在真实联调前需要执行一次）：
#   docker build -t project-doctor-target:latest .
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/target/slow-query-demo-*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["bash", "-c", "until (exec 3<>/dev/tcp/${DB_HOST:-db}/${DB_PORT:-3306}) 2>/dev/null; do echo waiting-for-db; sleep 2; done; exec java -jar /app/app.jar"]

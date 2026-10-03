# Multi-stage build for the Project Doctor isolated environment.
#
# The isolated compose rendered by Project Doctor runs this app on the `internal`
# network with the following connection variables injected:
#   DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD
# The app listens on 8080 (published to the isolated host port by the compose file).
#
# Build the image once before preparing the environment:
#   docker build -t project-doctor-target:latest .
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
# `*.jar` matches only the repackaged executable jar; the `.jar.original` does not.
COPY --from=build /workspace/target/slow-query-demo-*.jar app.jar
EXPOSE 8080
# Wait for the database port before starting; Spring initialises the schema and
# seeds the test data on first boot, so the DB must already accept connections.
ENTRYPOINT ["bash", "-c", "until (exec 3<>/dev/tcp/${DB_HOST:-db}/${DB_PORT:-3306}) 2>/dev/null; do echo waiting-for-db; sleep 2; done; exec java -jar /app/app.jar"]

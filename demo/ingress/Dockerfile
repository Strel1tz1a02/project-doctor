FROM maven:3.9-eclipse-temurin-17@sha256:1a352420f7aba21f5ad08df31bab55f74c013fb491f1ae8ab1dd7ff9ed698584 AS build
WORKDIR /build
COPY Ingress.java .
RUN javac Ingress.java
FROM eclipse-temurin:17-jre@sha256:207ecae0b2b104dfc6dfa763d1e9cd2041cb344800a180e24cb1a28ed533ff90
COPY --from=build /build/Ingress.class /relay/Ingress.class
USER 10001:10001
HEALTHCHECK NONE
ENTRYPOINT ["java", "-cp", "/relay", "Ingress"]

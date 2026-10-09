ARG MAVEN_IMAGE_TAG=3.10.0-eclipse-temurin-25-alpine
ARG JRE_IMAGE_TAG=25.0.4_7-jre-alpine

FROM maven:${MAVEN_IMAGE_TAG} AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -B -q -e dependency:go-offline || true
COPY src ./src
RUN mvn -B -q -e package

FROM eclipse-temurin:${JRE_IMAGE_TAG}
RUN mkdir -p /app /logs && chmod 0777 /logs
COPY --from=build /build/target/receiver.jar /app/
COPY --from=build /build/target/lib /app/lib
USER 1000:1000
EXPOSE 8080
ENTRYPOINT ["java", "-XX:+UseSerialGC", "-Xmx128m", "-jar", "/app/receiver.jar"]

# ===== Build stage =====
# Se crea un contenedor temporal (mas pesado que JRE) para compilar el .jar
FROM eclipse-temurin:22-jdk-jammy AS build

# Se establece como directorio de trabajo la carpeta /app dentro de la raiz del contenedor temporal
WORKDIR /app

# Instalar dependencias necesarias
RUN apt-get update && apt-get install -y dos2unix tzdata

# Copiar archivos de Maven y resolver dependencias (se cachea si pom.xml no cambia)
# Al terminar de construir la imagen se cachea la capa de este contenedor JDK, entonces si se reutiliza este
# Dockerfile, no se vuelven a descargar las dependencias, amenos que algun archivo de estos haya cambiado (pom.xml, etc).
COPY .mvn/ .mvn
COPY mvnw pom.xml ./
RUN chmod +x mvnw && dos2unix mvnw
RUN ./mvnw dependency:resolve

# Copiar el resto del código fuente y compilar
COPY src ./src
RUN ./mvnw clean package -DskipTests

# ===== Runtime stage =====
# Como cambiamos de imagen, la anterior JDK sera eliminada pero se cachea la capa resultante.
FROM eclipse-temurin:22-jre-jammy
WORKDIR /app

# Instalar dependencias necesarias
RUN ln -snf /usr/share/zoneinfo/America/Argentina/Buenos_Aires /etc/localtime && \
    echo "America/Argentina/Buenos_Aires" > /etc/timezone

# Copiar el JAR desde la etapa de build
COPY --from=build /app/target/*.jar /app/app.jar

ENTRYPOINT ["java", "-jar", "/app/app.jar"]

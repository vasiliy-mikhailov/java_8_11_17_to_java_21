# Debug / Production
- Modificar en application.properties segun la necesidad:
    `spring.profiles.active=dev`
    `spring.profiles.active=prod`

Cuando esta en modo dev, usa la DB en memoria h2, por lo que no hay que preocuparse por correr contenedores de bases de datos.

## Compilar para producción
- Posicionarse en la carpeta raíz
```bash
sudo docker build -t backend .
```

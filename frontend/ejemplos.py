"""Texto de ejemplo del botón "Usar texto de ejemplo" (corto: entra de sobra en el límite de MAX_UPLOAD_MB)."""

TITULO_EJEMPLO = "Redes virtuales en Oracle Cloud Infrastructure (OCI)"

TEXTO_EJEMPLO = """Redes virtuales en Oracle Cloud Infrastructure (OCI)

Una Virtual Cloud Network (VCN) es una red privada y aislada dentro de Oracle Cloud donde corren tus recursos tecnológicos. Funciona de manera similar a un centro de datos virtual propio: vos definís el rango de direcciones IP, las reglas de tráfico y cómo se conectan los recursos entre sí. Por seguridad, ningún recurso dentro de una VCN es accesible desde el exterior salvo que lo habilites de forma explícita.

Subredes públicas y privadas

Una VCN se divide en subredes. Una subred pública permite que sus recursos tengan direcciones IP públicas y se conecten con internet; es el lugar típico para un balanceador de carga o un servidor web. Una subred privada aísla sus recursos para que no sean accesibles directamente desde internet; es el lugar ideal para bases de datos y servidores internos.

Componentes de conectividad

El Internet Gateway permite el tráfico entre la VCN e internet para los recursos de subredes públicas. El NAT Gateway permite que los recursos de una subred privada salgan a internet, por ejemplo para descargar actualizaciones, sin recibir conexiones entrantes. El Service Gateway permite acceder a servicios de Oracle, como Object Storage, sin pasar por internet.

Seguridad de red

Las Security Lists y los Network Security Groups (NSG) controlan qué tráfico puede entrar y salir. Una Security List se aplica a todas las instancias de una subred. Un NSG se aplica solo a los recursos que vos elijas, lo que permite reglas más específicas. Siempre se recomienda seguir el principio de mínimo privilegio: abrir únicamente los puertos necesarios, como el 443 para HTTPS.

Buenas prácticas

Mantené las bases de datos en subredes privadas. Usá un NAT Gateway cuando un recurso privado necesite salir a internet. Documentá los rangos de IP de cada subred para evitar solapamientos cuando conectes varias redes. Revisá periódicamente las reglas de seguridad y eliminá las que ya no se usen."""

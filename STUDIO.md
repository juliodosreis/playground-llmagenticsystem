# Studio con servidor local

`langgraph dev` levanta el servidor de agentes en `http://127.0.0.1:2024`, con los grafos
declarados en `langgraph.json`. La interfaz de Studio corre en `https://smith.langchain.com` y
pide los datos al servidor local desde el navegador. El error `Failed to initialize Studio`, con
el detalle `Failed to fetch`, indica que esa petición no llegó al servidor.

## Verificación del servidor

Dos comprobaciones separan el fallo del servidor del fallo del navegador. La primera, desde otra
terminal:

```bash
curl -s http://127.0.0.1:2024/ok
```

La segunda, abrir `http://127.0.0.1:2024/docs` en el navegador.

Con respuesta de `curl` y con `/docs` cargando, el servidor funciona y el bloqueo está en el
navegador: las secciones siguientes cubren ese caso. Sin respuesta de `curl`, el proceso terminó
al arrancar, y la causa aparece en la terminal donde corre `langgraph dev`. En este repositorio
las dos causas frecuentes son la falta del `.env` con la credencial del proveedor y un error de
importación en `travel_mas.agents.travel.graph:make_graph`.

El comando se ejecuta con `uv run`, porque `langgraph-cli[inmem]` está en el grupo `dev` de
`pyproject.toml` y vive en el `.venv/` del proyecto:

```bash
uv run langgraph dev
```

## Bloqueo de Chrome

Desde la versión 142, Chrome aplica la especificación Private Network Access sin alternativa de
respaldo, y corta las peticiones de una página HTTPS a un servidor HTTP en localhost. Los
síntomas de este caso:

- `langgraph dev` arranca y queda escuchando;
- `http://127.0.0.1:2024/docs` carga en el navegador;
- Studio muestra `Failed to initialize Studio ... TypeError: Failed to fetch`;
- la consola del navegador registra `Permission was denied for this request to access the
  'unknown' address space`.

El ajuste se hace en la pestaña de Studio:

1. abrir el icono del candado, a la izquierda de la barra de direcciones;
2. buscar la opción **Local network access**;
3. cambiarla de **Ask (default)** o de **Block** a **Allow**;
4. recargar la página.

## Túnel de Cloudflare

La opción `--tunnel` publica el servidor local por un túnel con HTTPS, y elimina el bloqueo en
cualquier navegador:

```bash
uv run langgraph dev --tunnel
```

El comando imprime una URL del tipo `https://algo.trycloudflare.com`. La conexión desde Studio
pide cinco pasos:

1. copiar la URL del túnel;
2. abrir `https://smith.langchain.com/studio/`;
3. pulsar **Connect to a local server**;
4. pegar la URL y añadirla a **Allowed Origins**;
5. pulsar **Connect**.

El cuarto paso es manual por una condición de Studio, que pide confirmación explícita antes de
conectarse a una URL externa. La documentación de LangChain registra que el túnel de Cloudflare
se desconecta de forma intermitente.

## Safari y Brave

Safari bloquea el tráfico HTTP en localhost, y el remedio es el túnel de la sección anterior.
Brave lo bloquea con los Shields activos, que se desactivan para el sitio desde el icono de
Brave en la barra de direcciones.

## Extensiones del navegador

Las extensiones que atienden puertos locales, entre ellas la de Ollama, interfieren con la
conexión a `127.0.0.1`. Una ventana de incógnito sin extensiones descarta esta causa. Con la
conexión funcionando ahí, las extensiones se reactivan de a una hasta encontrar la responsable.

## Puerto distinto

Con el puerto 2024 ocupado, el servidor arranca en otro puerto, y la URL de Studio deja de
apuntar al servidor. El parámetro `baseUrl` se corrige a mano con el puerto que imprimió la
terminal:

```
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025
```

## Referencia

Página de troubleshooting de Studio, con los casos de Chrome, Safari y Brave:
<https://docs.langchain.com/langsmith/troubleshooting-studio>

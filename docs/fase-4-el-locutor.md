# Fase 4 — El locutor

Objetivo de la fase: que la radio hable — guiones cortos entre tema y tema,
generados por un LLM local con fallback a plantillas, convertidos a voz con
Piper y cacheados. **Cerrada** — los 5 issues del milestone [Fase 4 — El
locutor](https://github.com/Skayear/SkyWave-FM/milestone/5) están resueltos
y el milestone está cerrado.

Principio rector de toda la fase: **la radio nunca se queda muda.** Cada
pieza tiene un camino de fallo que termina en "sigue la música", nunca en
silencio ni en un crash.

## Qué se hizo

### 1. Plantillas de guiones (issue [#15](https://github.com/Skayear/SkyWave-FM/issues/15))

`src/skywave/host/templates.py` — `render_script(ending, starting, now, rng)`:
despedida del tema saliente (si hay), presentación del entrante, coletilla
opcional con la franja horaria. Es el **piso** del locutor, no un extra:
por eso se construyó primero (la radio habla desde el día uno sin LLM) y
vive sin dependencias externas.

Las plantillas que mencionan el año solo entran al pool cuando el track lo
tiene — así nunca hay que rellenar un `{year}` inexistente (hay un test de
que "None" jamás aparece en un guion). `rng` y `now` inyectables, el mismo
patrón de la fase anterior.

Probar con la biblioteca real encontró un bug gramatical que los tests
sintéticos no vieron ("en esta la noche"): las franjas quedaron sin
artículo, todas femeninas, para que "esta {franja}" siempre concuerde.

### 2. Voz con Piper (issue [#16](https://github.com/Skayear/SkyWave-FM/issues/16))

`src/skywave/host/tts.py` — `Synthesizer`, con la voz `es_AR-daniela-high`
(~114MB, en `voices/` gitignoreado, se baja con
`uv run python -m piper.download_voices --download-dir voices es_AR-daniela-high`).

Desvío deliberado del plan original ("piper via subprocess"): se usa la
**API de Python** de piper porque el modelo ONNX se carga una sola vez y se
reusa — un proceso por guion lo recargaría cada vez (segundos por
intervención). El WAV sale en el formato nativo de la voz (22050Hz mono):
no hace falta convertirlo, el `Decoder` del mixer resamplea todo a 44100Hz
estéreo de todos modos.

Latencia medida: ~1.2s de carga del modelo (una vez), ~1.8s por síntesis.
La voz quedó aprobada para pruebas; darle más expresividad ("ímpetu") es
investigación pendiente — opciones anotadas: ajustar `length_scale` /
`noise_scale` de Piper, o probar otras voces.

### 3. Cache por hash (issue [#17](https://github.com/Skayear/SkyWave-FM/issues/17))

`src/skywave/host/cache.py` — `VoiceCache`: cache-aside con
`sha256(voz + texto)` como nombre del WAV. La función de síntesis se
**inyecta como `Callable`** (la firma de `Synthesizer.synthesize`), así los
tests usan una fake con contador y no necesitan Piper. La voz forma parte
de la clave: cambiar de voz no sirve WAVs de la anterior.

Escritura atómica (temporal + `Path.replace`, atómico en POSIX): una
síntesis que explota a mitad de camino no deja un WAV corrupto que el cache
serviría para siempre.

Medido: ~1.2s la primera síntesis, ~0.1ms el hit de cache.

### 4. Guiones con LLM (issue [#18](https://github.com/Skayear/SkyWave-FM/issues/18))

`src/skywave/host/scripts.py`:

- **`ScriptGenerator` es un `Protocol`** — duck typing tipado: cualquier
  clase con la firma de `generate()` califica, sin heredar de nada. Es lo
  que permite intercambiar Ollama / API de Claude / plantillas sin tocar
  el resto -- la implementación con API de Claude llegó después, ver
  "Seguimiento posterior a la fase" más abajo (issue #34).
- **`OllamaGenerator`** contra la API HTTP local (`urllib` de la stdlib —
  una sola llamada POST no justifica una dependencia). Modelo:
  `llama3.2:3b`.
- **`ResilientScriptWriter`**: intenta el primario; ante cualquier
  excepción, warning de una línea y plantillas (traceback solo en debug —
  con Ollama apagado pasa en cada tema y no es un bug).

Iterar el prompt con el modelo real fue necesario: la primera versión
inventaba películas y anécdotas (alucinaciones típicas de un 3B). Se
agregó la instrucción explícita de no inventar y `num_predict: 80` — menos
tokens también significa menos latencia en CPU (~13s → ~5-11s por guion).

### 5. Al aire (issue [#19](https://github.com/Skayear/SkyWave-FM/issues/19))

En el loop de `skywave play`: guion → WAV cacheado → suena → tema.
`--sin-locutor` lo apaga; si falta la voz de Piper la radio arranca igual
avisando. Nada del locutor puede voltear la música: cualquier excepción del
pipeline de voz se reporta y el tema entra igual.

### 6. El locutor lee los saludos de los oyentes (issue [#36](https://github.com/Skayear/SkyWave-FM/issues/36))

Retomado después de Fase 7 (los saludos de `POST /greetings`, issue #31,
necesitaban alguien que los lea). Mismo patrón que las publicidades
(`scheduler/ads.py`), pero la síntesis es en vivo, no pre-renderizada —
un saludo es texto libre de un oyente, no se puede curar a mano de
antemano.

- **Persistencia** (`web/greetings.py`): columna `read_at` nueva en la
  tabla `greetings`, con una migración real en `ensure_schema()`
  (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN` si falta) — `CREATE
  TABLE IF NOT EXISTS` no suma columnas a una tabla que ya existe, y el
  `skywave.db` de Pablo ya tenía saludos guardados desde #31. Probado
  contra ese archivo real antes de seguir. `unread_greetings()` trae los
  pendientes en orden FIFO; `mark_greeting_read()` los saca de la cola.
- **Guion fijo** (`host/templates.py`): `render_greeting_script(mensaje)`
  — sin LLM, el texto ya lo escribió una persona, generarlo de nuevo no
  tiene sentido. Solo una introducción corta que lo enmarca.
- **Rotación** (`scheduler/greetings.py`, nuevo): `should_read_greeting`
  es la mitad de simple que `should_play_ad` — no hace falta elegir
  *cuál* leer (FIFO puro), solo *cuándo* toca revisar la cola.
- **Wiring en `cli.py`**: `--saludos/--sin-saludos`, `--saludos-every N`
  (default 5). Requiere que el locutor esté prendido y con voz
  disponible (`host is not None`) — un saludo se sintetiza con la misma
  `VoiceCache`/Kokoro del locutor, no tiene sentido levantar un segundo
  motor de voz solo para esto. Se inserta entre temas como una
  publicidad (`play_track`, no ducking), pero si no hay saludos
  pendientes el contador no se resetea: sigue chequeando en cada tema
  hasta que llega uno.

Probado con tests (migración sobre una tabla vieja simulada, orden FIFO,
`should_read_greeting`) y a mano al aire con `--saludos-every 1`: el
locutor leyó un saludo mandado por `POST /greetings` entre dos temas
reales, y quedó marcado `read_at` en `skywave.db`.

## Ajustes no anticipados

- **Aire muerto de ~12s por intervención** cuando el guion se genera en
  vivo (LLM en CPU + síntesis). La solución correcta — pre-generar la
  intervención en un hilo mientras suena el tema anterior — quedó como
  issue [#20](https://github.com/Skayear/SkyWave-FM/issues/20) en Fase 5,
  que de todos modos retoca cómo sale el locutor al aire (ducking).
- **La carga en frío de Ollama** (~2GB a RAM) supera con comodidad un
  timeout de 15s: el default subió a 30s.
- **`Broken pipe` real al aire, encontrado por Pablo después de cerrar la
  fase.** El `source-timeout` default de Icecast (10s) es más corto que lo
  que tarda Ollama en generar un guion: mientras genera, el encoder no le
  escribe nada al pipe, Icecast lo desconecta por inactividad, y el
  próximo `write()` explota. Se corrigió generando un `icecast.xml` propio
  con `source-timeout` en 60s (la imagen no lo expone como variable de
  entorno) — ver `config/icecast.xml.template` y
  `scripts/render-icecast-config.sh`. La pre-generación del issue #20
  también resuelve esto de raíz (el encoder nunca queda esperando), pero
  el timeout más alto es la red de seguridad mientras tanto.
- **Alucinación real al aire, encontrada por Pablo después de cerrar la
  fase (2026-08-27).** El guion decía "El Amante" de Juan Luis Guerra
  mientras sonaba "Keep On Loving You" de REO Speedwagon: `llama3.2:3b`
  inventó un tema completamente distinto pese a tener el título y artista
  reales en el prompt — la instrucción de "no inventes" (agregada cuando
  se detectó que inventaba anécdotas, más arriba) no alcanza como garantía
  con un modelo tan chico. Se corrigió reforzando el prompt y agregando
  `_mentions_track()` en `host/scripts.py`: valida que el título real
  aparezca en el texto generado, y si no, lo descarta como inválido —
  `ResilientScriptWriter` cae a plantillas, el mismo mecanismo que ya
  existía para Ollama caído o con timeout.
- **Piper reemplazado por Kokoro (2026-08-27).** Pablo pidió comparar
  alternativas de voz en ramas separadas (issue #24): `spike/xtts-v2` y
  `spike/kokoro`, mismo guion sintetizado con las tres para comparar en
  igualdad de condiciones. Veredicto a la escucha: Kokoro suena mejor.
  También fue ~10x más rápido que XTTS-v2 en CPU (~9s vs ~91s por
  guion) — sigue siendo más lento que Piper (~1.8s), pero la voz ganó.
  `host/tts.py`'s `Synthesizer` mantiene la misma interfaz
  (`synthesize(text, wav_path) -> Path`), así que nada río abajo
  (`VoiceCache`, `render_ads()`) tuvo que cambiar. Detalle completo de
  la comparación y de la instalación (por qué hace falta el índice
  CPU-only de PyTorch, el bug de `transformers` en coqui-tts, etc.) en
  los commits de las ramas spike y en los comentarios del issue #24.
- **`_mentions_track()` tenía sus propios falsos positivos (2026-08-27).**
  Pablo reportó que 2 de 2 guiones cayeron a plantillas en una corrida
  real; midiendo la tasa de rechazo a mano contra la biblioteca completa,
  buena parte no eran alucinaciones sino la validación siendo demasiado
  estricta: (1) títulos con sufijo entre corchetes ("Mechanix [2002
  Remix]") — el LLM decía correctamente "la versión remezclada de
  'Mechanix'" pero se exigía el corchete literal, que nadie dice en voz
  alta; (2) comillas tipográficas — títulos de nombres de archivo estilo
  Apple Music usan comilla curva ("Ridin’ the Storm Out", U+2019) pero el
  LLM escribe con apóstrofo recto, mismo texto para un oído humano pero
  distinto para un substring exacto. Con `_base_title()` y
  `_QUOTE_NORMALIZE` arreglando ambos, y `temperature` bajada de 0.9 a
  0.6 (medido: ~35%→~25% de rechazo genuino, misma semilla de prueba), la
  tasa de alucinación real que queda es el piso de un modelo de 3B —
  "Here Is the News" en particular parece confundirlo sistemáticamente
  (el título suena a instrucción). Se acepta ese piso: lo que sale al
  aire nunca miente, aunque a veces sea una plantilla en vez del LLM.
- **Pausas rotas por saltos de línea, encontrado por Pablo (2026-08-27).**
  Kokoro parte el texto en fragmentos por cada `\n` (su `split_pattern`
  default) y sintetiza cada uno por separado, pegándolos después sin
  silencio entre medio. Los `.txt` de publicidades de Fase 6 están
  escritos con saltos de línea "de lectura" (ajustados a ~70 caracteres
  para que el archivo no tenga líneas eternas) — Kokoro los tomaba como
  cortes de oración reales, y el resultado sonaba cortado en lugares
  arbitrarios. `Synthesizer.synthesize()` ahora normaliza el texto
  (colapsa cualquier corrida de espacios/saltos de línea a uno solo)
  antes de sintetizar.
- **Títulos/artistas en inglés mal pronunciados, mismo pedido de Pablo
  (2026-08-27).** Con voz en español, Kokoro fonemiza todo el texto con
  reglas de español — el motor (`misaki`) tiene desactivada la detección
  automática de idioma extranjero de espeak-ng
  (`language_switch='remove-flags'`). Investigando el código de `misaki`
  se confirmó que los alfabetos fonéticos de español e inglés son
  compatibles (ambos IPA), así que se puede fonemizar el título/artista
  aparte con el motor de inglés (`misaki.en.G2P`) y empalmarlo a mano en
  la cadena de fonemas en español antes de sintetizar con
  `KPipeline.generate_from_tokens()`. Implementado en
  `Synthesizer.synthesize(..., english_terms=[...])`, con
  `english_terms_for()` en `host/scripts.py` armando la lista a partir
  de los `Track` reales (mismo tratamiento de corchetes/comillas que
  `_mentions_track`). Si el guion es muy largo para el límite del modelo
  (510 caracteres de fonemas), cae a la síntesis normal en vez de perder
  la intervención entera.

## Seguimiento posterior a la fase

### Generador de guiones con la API de Claude (issue [#34](https://github.com/Skayear/SkyWave-FM/issues/34))

`ScriptGenerator` (`Protocol`) ya dejaba la puerta abierta a un segundo
generador además de `OllamaGenerator`. `ClaudeGenerator`
(`src/skywave/host/scripts.py`) la implementa contra la Messages API del
SDK oficial `anthropic`, reusando `_prompt()` y `_mentions_track()` tal
cual -- no son específicas de Ollama, así que no hacía falta duplicarlas.
Mismo criterio de fallas: cualquier problema (red, respuesta vacía, tema
inventado) sale como excepción, y quien decide qué hacer con eso sigue
siendo `ResilientScriptWriter`, no esta clase.

Modelo default: `claude-haiku-4-5-20251001` — el más barato/rápido de la
familia, de sobra para una frase de locutor entre temas.

**El SDK `anthropic` quedó como dependencia opcional**
(`pyproject.toml`, `[project.optional-dependencies]`, extra `claude`,
`uv sync --extra claude`), no como dependencia dura de todo el proyecto:
la mayoría de las corridas usan Ollama (gratis, local) y no tiene sentido
forzar el paquete a quien nunca usa `--generador claude`. Por la misma
razón el `import anthropic` no va arriba del módulo `scripts.py`, sino
adentro de `ClaudeGenerator.__init__` -- recién cuando alguien de verdad
instancia esta clase, así el resto de `skywave` importa igual sin el
extra instalado.

**Elección de generador**: `skywave play --generador ollama|claude`
(default `ollama`). Sin `ANTHROPIC_API_KEY` en el entorno y pidiendo
`--generador claude`, `_build_locutor()` avisa y arranca directo con
plantillas -- ni siquiera intenta instanciar `ClaudeGenerator` una vez.
Con la key puesta, si falla en vivo cae a plantillas igual que con
Ollama (mismo `ResilientScriptWriter`). Esto obligó a mover el
`load_dotenv()` que antes solo corría en `_icecast_url()` (más abajo en
el flujo de `play()`) a `_build_locutor()`, para que la key ya esté en
`os.environ` cuando se hace ese chequeo.

Probado con tests (`tests/host/test_scripts.py`): cliente de Anthropic
falso (nunca pega a la API real), guion normal, tema inventado,
respuesta vacía y error de red.

**Nota sobre el issue**: un comentario anterior de otra sesión afirmaba
que esto ya estaba implementado en un commit (`e7f37b5`) que en realidad
no existe en el repo -- ni en `git log`, ni en el reflog, ni como commit
huérfano. No hay forma de saber qué pasó (¿otro clon del repo?, ¿se
perdió al re-clonar?), pero acá no había nada de `ClaudeGenerator` para
retomar. Se documenta para que quede registrado el hallazgo.

**Criterio de aceptación "probado a mano al aire"**: sigue pendiente de
tener una `ANTHROPIC_API_KEY` real a mano.

## Para estudiar antes de Fase 5

Fase 5 (mezcla de verdad) es la fase numpy: el audio como arrays de
`int16`, crossfade como interpolación entre dos señales, ducking como
atenuar la música bajo la voz. También threading con resultados
(pre-generación del issue #20).

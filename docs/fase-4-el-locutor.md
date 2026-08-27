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
  el resto (la implementación con API de Claude queda pendiente; la
  interfaz ya la contempla).
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

## Para estudiar antes de Fase 5

Fase 5 (mezcla de verdad) es la fase numpy: el audio como arrays de
`int16`, crossfade como interpolación entre dos señales, ducking como
atenuar la música bajo la voz. También threading con resultados
(pre-generación del issue #20).

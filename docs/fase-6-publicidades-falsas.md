# Fase 6 — Publicidades falsas

Objetivo de la fase: publicidades ficticias estilo GTA, curadas a mano una
sola vez, nunca generadas en vivo. **Cerrada** — los 4 issues del milestone
[Fase 6 — Publicidades
falsas](https://github.com/Skayear/SkyWave-FM/milestone/7) están resueltos
y el milestone está cerrado.

Decisión de fondo (ya tomada en CLAUDE.MD antes de arrancar la fase): "se
generan y curan una sola vez a mano, se renderizan a WAV en `assets/ads/`
y el scheduler las rota. No se generan en vivo." Todo el diseño de la fase
sale de ahí — es la contraparte del locutor: el locutor sí improvisa en
vivo (con fallback), las publicidades nunca.

## Qué se hizo

### 1. Curar y renderizar a WAV (issue [#25](https://github.com/Skayear/SkyWave-FM/issues/25))

Nuevo paquete `src/skywave/ads/`. `render_ads(scripts_dir, out_dir,
synthesize)` toma cada guion `.txt` curado a mano en `assets/ads/scripts/`
y lo sintetiza a `assets/ads/*.wav` — mismo patrón de inyección de
dependencias que `VoiceCache` de Fase 4 (la función de síntesis se pasa
como `Callable`, no una clase concreta, para poder testear sin Piper
real). Nuevo comando `skywave render-ads`, paso manual/offline.

3 publicidades de prueba curadas a mano (productos ficticios: Mate Turbo,
Seguros El Zorro, Colchones Nube Nueve), en tono GTA/rioplatense acorde a
la identidad de SkyWave FM. Los `.txt` se versionan, los `.wav` quedan
gitignoreados (`assets/ads/*.wav`, regla que ya estaba anticipada en
`.gitignore` desde antes de arrancar la fase).

### 2. Producir el jingle (issue [#26](https://github.com/Skayear/SkyWave-FM/issues/26))

`ads/jingle.py` genera el colchón musical y los stingers con **numpy**
(tonos senoidales) en vez de samples de audio externos — no hay una
fuente de audio royalty-free integrada al proyecto, y sigue la misma
línea de Fase 5 de aprender audio componiendo señales en vez de depender
de assets de terceros.

- `generate_bed()`: acorde de Do mayor sostenido, atenuado (0.12 de
  amplitud) para no competir con la voz. Fade-in/out solo en los bordes
  (`_fade_edges()`, nueva) — a diferencia de `fade_in`/`fade_out` de
  `audio.py`, que rampean la señal entera de punta a punta (pensadas para
  crossfade entre temas, no para sostener un colchón).
- `generate_stinger()`: arpegio ascendente cortito tipo campanita de
  radio, de apertura y cierre.
- `produce_ad()`: decodifica la voz recién sintetizada con el `Decoder`
  del mixer (normaliza a 44100Hz estéreo sin importar el formato nativo
  de Piper), la mezcla con el colchón (`mix()` de `audio.py`, clipping
  controlado) y la envuelve entre los dos stingers.

`render_ads()` de la issue anterior ahora acepta un `produce` opcional
que se llama después de sintetizar, sin romper su firma ni sus tests.

### 3. Rotación en el scheduler (issue [#27](https://github.com/Skayear/SkyWave-FM/issues/27))

`scheduler/ads.py`: `pick_next_ad()` reusa el mismo algoritmo de
relajación de ventana que `pick_next()` de temas musicales (Fase 3) — si
la ventana de no-repetición deja el pool vacío, se achica de a uno hasta
encontrar candidatos, con el mismo último recurso de no repetir la
publicidad que sonó recién. Sin ventana por "artista": acá la publicidad
entera es la unidad, y el default de ventana es más chico (2, no 3)
porque con pocas publicidades curadas a mano una ventana grande las
agotaría en seguida.

`should_play_ad(tracks_since_last_ad, every=8)` separa la política de
"cuándo" de "cuál" — el contador lo lleva el llamador.

### 4. Al aire (issue [#28](https://github.com/Skayear/SkyWave-FM/issues/28))

En el loop de `skywave play`: cada `--ads-every` temas (default 8), suena
una publicidad después del tema, antes de pasar al siguiente. Decisiones
tomadas al conectar todo:

- La publicidad ya viene producida con sus propios fades (stinger de
  apertura/cierre): no se funde por crossfade con la cola del tema
  anterior, se escribe tal cual y arranca la publicidad limpia.
- `now_playing` en SQLite **no** refleja la publicidad a propósito: sigue
  mostrando el último tema real. Dura segundos y no es "programación" — la
  futura web de Fase 7 no necesita saberlo.
- `--sin-publicidades` las apaga. Sin publicidades renderizadas (nunca se
  corrió `skywave render-ads`), la radio sigue igual, sin publicidades —
  mismo principio de siempre: una pieza opcional que falta no la deja
  muda.

## Probado a mano

Con Icecast + ffmpeg reales: sesión de `skywave play --ads-every 1` de
260s que atravesó un tema completo (~190s), una publicidad, y arrancó el
siguiente tema — sin tracebacks ni procesos huérfanos. Falta la escucha
real de Pablo del colchón/stinger de las 3 publicidades de prueba
(mandadas aparte) — la mecánica de producción y de rotación están
verificadas, el criterio de "suena bien" es suyo.

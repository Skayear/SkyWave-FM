# Fase 5 — Mezcla de verdad

Objetivo de la fase: que suene como una radio de verdad — nada de cortes en
seco entre temas ni voz pisando la música en silencio. **Cerrada** — los 4
issues del milestone [Fase 5 — Mezcla de
verdad](https://github.com/Skayear/SkyWave-FM/milestone/6) están resueltos
y el milestone está cerrado.

Es la fase de numpy: todo el PCM que hasta ahora viajaba como bytes opacos
entre `Decoder` y `Encoder` ahora también se puede tratar como arrays y
componer — ganancia, fades, mezcla de dos señales — y de esas primitivas
salen crossfade y ducking.

## Qué se hizo

### 1. Utilidades de audio con numpy (issue [#21](https://github.com/Skayear/SkyWave-FM/issues/21))

`src/skywave/mixer/audio.py`: conversión bytes s16le ↔ `np.ndarray` int16
con shape `(frames, 2)`, `apply_gain` (con cuidado del *wraparound*: pasar a
float64 antes de escalar y clipear al rango de int16 al volver — escalar
directo en int16 desborda en vez de saturar), `mix` (suma con clipping), y
`fade_in`/`fade_out` como rampas lineales de dos puntos, expresadas sobre
`apply_envelope` — una generalización que aplica un factor de ganancia
*distinto por frame* en vez de uno constante, la pieza que después reusa el
ducking para su rampa de tres tramos (baja-sostiene-sube).

Lógica pura y determinística, con tests sobre señales chicas armadas a
mano — la primera vez en el mixer que el audio se prueba con pytest en vez
de solo a mano, justamente porque acá no hay ffmpeg de por medio todavía.

### 2. Crossfade entre temas (issue [#22](https://github.com/Skayear/SkyWave-FM/issues/22))

`src/skywave/mixer/player.py`: `play_track` ahora puede retener los
últimos `crossfade_seconds` de PCM en vez de escribirlos, y devolverlos —
el llamador se los pasa como `incoming_tail` al siguiente `play_track`, que
los funde (fade-out de la cola + fade-in del arranque, mezclados) con el
inicio de la próxima pista en vez de cortar en seco.

El punto más delicado fue no reinventar el pacing: la cola retenida ya se
decodificó a ritmo real (`Decoder -re`), así que fundirla no debía ni
duplicar tiempo de aire ni saltearlo — de ahí `_take()`, un helper genérico
que junta exactamente N bytes de un iterador de chunks y devuelve el resto
como otro iterador para seguir consumiéndolo sin perder nada.

En `skywave play`, el crossfade aplica entre temas consecutivos. Si el
locutor habla en el medio, la cola pendiente se escribe tal cual (sin
fundir) antes de que arranque el colchón del próximo tema — fundir música
con voz es ducking (#23), no esto.

### 3. Ducking: la música de colchón bajo la voz (issue [#23](https://github.com/Skayear/SkyWave-FM/issues/23))

`play_ducked()`: mezcla el guion del locutor (a volumen pleno) con el
arranque del *próximo* tema — no la cola del que termina — atenuado por
default, y sigue con el resto de la pista a volumen normal. Reemplaza la
voz en seco de Fase 4.

La decisión de qué usar como colchón (arranque del entrante vs. cola del
saliente) la dejaba abierta el issue; se fue por el arranque del entrante
porque es lo que hace un locutor de radio real — habla presentando el tema
que viene, no despidiendo el que se fue.

### 4. Pre-generar la intervención del locutor (issue [#20](https://github.com/Skayear/SkyWave-FM/issues/20))

`_prepare_next()` en `cli.py`: elige el próximo tema, genera su guion y lo
sintetiza a WAV, todo en un `ThreadPoolExecutor(max_workers=1)` — corre en
un hilo de fondo mientras el tema actual suena en tiempo real, que le sobra
de margen frente a los ~5-13s que tarda Ollama + Piper. Cuando el tema
termina, la intervención ya está lista y entra al toque con `play_ducked`,
sin el aire muerto que medía la Fase 4.

El primer tema de la sesión se prepara de forma síncrona antes de salir al
aire (mismo trade-off de siempre: un poco de espera al arrancar es mejor
que quedarse muda en el medio). Ctrl+C no espera una preparación en curso
(`prep_pool.shutdown(wait=False, cancel_futures=True)`) — puede estar a
mitad del timeout de 30s de Ollama y no tiene sentido bloquear el corte por
eso.

Esta issue también resuelve de raíz el bug de `Broken pipe` de Fase 4 (el
`source-timeout` de Icecast más corto que la latencia de Ollama): con el
guion listo de antemano, el encoder nunca vuelve a quedar esperando en
seco a mitad de una generación. El timeout de 60s en `icecast.xml` queda
igual como red de seguridad.

## Ajustes no anticipados

- Al principio, ninguno grande — la fase se apoyó en el diseño de Fase 2
  (Decoder/Encoder por PCM crudo) más de lo esperado: ni crossfade ni
  ducking necesitaron tocar `Decoder`/`Encoder`, todo se resolvió
  componiendo `audio.py` con `_take()`/`_stream_with_held_tail()` en
  `player.py`.
- **El ducking original se solapaba con el final de la frase, encontrado
  por Pablo al aire (2026-08-28).** El colchón de música duraba
  *exactamente* lo mismo que el audio del locutor, y la rampa de subida
  de vuelta a volumen pleno (0.5s) vivía adentro de esa misma ventana —
  los últimos instantes de esa rampa se solapaban con el final del habla,
  así que la música ya sonaba fuerte otra vez mientras el locutor todavía
  estaba terminando de hablar. Encima `duck_gain=0.25` dejaba la música
  bastante presente incluso en el tramo sostenido, tapando parte de la
  voz. Se corrigió con ataque rápido / release lento (la práctica habitual
  de ducking en audio): `_duck_envelope()` y `_duck_mix()` ahora separan
  `attack_frames` (bajada, dentro del habla) de `release_frames` (subida,
  en un tramo aparte *después* de que el habla ya terminó, sobre música
  sin voz encima). `play_ducked()` pide de más a `music_path` (el habla
  más `release_seconds` extra) para tener ese margen. Defaults nuevos:
  `duck_gain=0.15` (antes 0.25, música más abajo para que la voz se
  entienda mejor), `attack_seconds=0.2` (antes 0.5, cae rápido apenas
  arranca la voz) y `release_seconds=1.0` (nuevo, la música tarda un
  segundo en volver a subir, ya en silencio de por medio).
- **Ni siquiera con eso alcanzaba: Pablo pidió, al aire de nuevo
  (2026-08-28), que el locutor arranque hablando un tramo *totalmente*
  solo, sin nada de música todavía — no solo atenuada, en silencio — con
  una proporción concreta: 75% del habla sin música, 25% con colchón.
  `_duck_envelope()` pasó de tres a cuatro tramos: silencio total
  (`solo_ratio` del habla), sube como colchón (`fade_in_frames`,
  reemplaza al viejo `attack_frames` — ahora es una subida desde 0 en vez
  de una bajada desde 1.0, porque ya no hay "música a full" al arrancar
  el habla), sostiene, y el release sigue igual que antes (aparte,
  después del habla). `duck_gain` bajó de nuevo, 0.15→0.10, porque seguía
  tapando la voz incluso en el tramo sostenido. Constantes nuevas:
  `DEFAULT_DUCK_SOLO_RATIO=0.75`, `DEFAULT_DUCK_FADE_IN_SECONDS=0.2`
  (renombrado de `DEFAULT_DUCK_ATTACK_SECONDS`, mismo valor).
- **Aire muerto real de varios segundos entre que termina un tema y
  arranca el locutor, encontrado por Pablo al aire (2026-08-28, mismo
  día).** No era un problema de mezcla sino de pacing: `Decoder` siempre
  usa `ffmpeg -re` para leer a ritmo real (issue #8), pero `play_ducked`
  lo usaba también para decodificar el WAV de la voz — que se junta
  entero en memoria antes de mezclarlo (`b"".join(...)`), así que pacear
  esa lectura no servía para nada más que bloquear: el `encoder` no
  recibía ni un byte durante toda la duración real del guion (varios
  segundos) antes del primer `write()`. Encima, `play_ducked` armaba el
  colchón entero (voz + música + release) en memoria y recién ahí lo
  escribía de una — el mismo problema, aplicado también a la ventana de
  música que tenía que llegar a ritmo real antes de poder mezclarla.
  Arreglado en dos partes: `Decoder` ganó un flag `realtime: bool = True`
  (`False` desactiva el `-re`) usado tanto acá como en
  `ads/jingle.py::produce_ad()` (mismo patrón: decodifica la voz entera
  para mezclarla, ahí también sobraba el pacing, aunque ese caso no genera
  aire muerto por ser offline). Y `_duck_mix()` (que juntaba todo antes de
  devolver un solo bloque) se reemplazó por `_duck_chunks()`: mezcla la
  música con la voz *a medida que ffmpeg entrega cada chunk*, ya a ritmo
  real, en vez de esperar a juntar el colchón entero — así el primer byte
  sale al aire casi al instante en vez de después de un bloqueo de varios
  segundos. `play_ducked()` quedó más simple además: ya no necesita
  `_take()` para recortar el colchón de antemano.

## Probado a mano

Con Icecast + Ollama + Kokoro corriendo de verdad: sesiones de `skywave
play` de hasta 150s que atravesaron transiciones completas entre temas
(incluida la más corta de la biblioteca, "Dear Friends" de Queen, ~69s),
sin tracebacks ni procesos `ffmpeg` huérfanos al cortar. La confirmación
auditiva de Pablo escuchando el fundido y el colchón al aire (2026-08-28)
fue lo que encontró el bug de solapamiento de arriba — corregido y
pendiente de una segunda pasada de oído.

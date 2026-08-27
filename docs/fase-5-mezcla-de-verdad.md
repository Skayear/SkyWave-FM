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
arranque del *próximo* tema — no la cola del que termina — atenuado a 0.25
por default con rampas de bajada y subida de 0.5s, y sigue con el resto de
la pista a volumen normal. Reemplaza la voz en seco de Fase 4.

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

Ninguno grande — la fase se apoyó en el diseño de Fase 2 (Decoder/Encoder
por PCM crudo) más de lo esperado: ni crossfade ni ducking necesitaron
tocar `Decoder`/`Encoder`, todo se resolvió componiendo `audio.py` con
`_take()`/`_stream_with_held_tail()` en `player.py`.

## Probado a mano

Con Icecast + Ollama + Piper corriendo de verdad: sesiones de `skywave
play` de hasta 150s que atravesaron transiciones completas entre temas
(incluida la más corta de la biblioteca, "Dear Friends" de Queen, ~69s),
sin tracebacks ni procesos `ffmpeg` huérfanos al cortar. Falta la
confirmación auditiva final de Pablo escuchando el fundido y el colchón al
aire — la mecánica y el pipeline están verificados, el oído todavía no.

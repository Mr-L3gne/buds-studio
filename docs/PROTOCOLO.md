# Protocolo de controle dos fones (Galaxy Buds Core / SM-R410)

Documento da Fase 1: análise estática de dois APKs Android, feita para
interoperabilidade (usar no Linux fones que o usuário já possui).

- **Fonte de verdade:** código descompilado dos APKs.
- **Nada foi executado:** o APK não rodou e nenhum fone foi conectado.
- **Marcação [INFERIDO]:** indica dedução, sempre com a justificativa ao lado.
  Tudo o que não tem a marca foi lido diretamente do código.

---

## 0. Artefatos analisados e método

| APK | Pacote | Versão (versionCode) | minSdk/targetSdk | SHA-256 |
|---|---|---|---|---|
| Galaxy Wearable | `com.samsung.android.app.watchmanager` | 2.2.72.26092361 (2126092361) | 26 / 36 | `42a35b77e048876133088acc4feaebae2f763f5c37841be55733cfe1335b9f9d` |
| Plugin "piano" | `com.samsung.accessory.pianomgr` | 8.5.26070351 (2026070351) | 30 / 36 | `8fa6e450f3c83c90dc70679f094b5f7cae645afc8a243bd48d0e0741a877c5b5` |

### Ferramentas

- **REA** (`rea-agents@6.3.0`) com o provider Android JADX headless 0.7.1. O JAR foi verificado pelo
  SHA-256 que o próprio REA fixa: `6e5eacf5…ff75`. JDK 21.
- Na sessão, o REA via MCP não tinha `REA_JADX_MCP_JAR` configurado. Por isso, todas as chamadas
  do REA foram feitas pela **CLI do REA** (`rea inspect-android-package`,
  `search-android-classes` e `inspect-android-method`), com as variáveis de ambiente
  definidas na própria chamada.
- **Exceção avisada:** cerca de 6.000 das 7.189 classes do plugin estão ofuscadas pelo R8
  (nomes como `g8.a`, `e8.G`). As ferramentas Android do REA trabalham com nome exato de
  classe ou método e não buscam por strings. Para *localizar* o protocolo, os fontes
  foram exportados com a **mesma API JADX contida no JAR do REA** (`jadx.api.JadxDecompiler`)
  e pesquisados com grep. Cada método-chave foi depois **confirmado pelo REA**
  (`inspect-android-method`); os IDs de Evidence estão na seção 9.
- Os nomes de classe neste documento são os **originais do DEX** (por exemplo `g8.a`).
  Ao exportar, o JADX renomeia alguns pacotes (`g8` → `p077g8`, `g8.a` → `C0537a`).

### Papel de cada APK

| APK | Papel | Contém o protocolo do fone? |
|---|---|---|
| Galaxy Wearable (`watchmanager`) | Gerenciador genérico. Descobre o dispositivo, identifica o modelo pelo nome Bluetooth, escolhe o plugin, instala e inicia o plugin. | **Não.** Não há código de EQ nem de mensagens SPP. Só há a checagem de UUIDs para reconhecer "é um Buds Samsung". |
| Plugin `pianomgr` | Gerenciador específico do **Galaxy Buds Core**. Abre o socket SPP, implementa o protocolo, a UI de EQ, ANC/ambiente, toques, bateria e FOTA. | **Sim**, por completo. |

### Modelo atendido pelo plugin

- `app_name`/`device_name` = **"Galaxy Buds Core"**, em `res/values/strings.xml`.
- URLs de manual: `…/m-manual/…/SM-R410/…` (classe `A8.d`). O modelo é o **SM-R410**.
- Build: `BuildConfig.FLAVOR_model = "piano"`, assinatura `HearableMgrPiano-…`.
- No Galaxy Wearable, `b7.l` mapeia `"Galaxy Buds Core"` → `com.samsung.accessory.pianomgr`.
  Cada modelo de Buds tem um plugin próprio:

| Nome BT (chave em `b7.l`) | Plugin |
|---|---|
| Galaxy Buds | `fridaymgr` |
| Galaxy Buds+ | `popcornmgr` |
| Galaxy Buds Live | `neobeanmgr` |
| Galaxy Buds Pro | `atticmgr` |
| Galaxy Buds2 | `berrymgr` |
| Galaxy Buds2 Pro | `zenithmgr` |
| Galaxy Buds FE | `pearlmgr` |
| Galaxy Buds3 / Buds3 Pro | `jellymgr` / `paranmgr` |
| **Galaxy Buds Core** | **`pianomgr`** ← analisado |

**Variações por modelo:** este documento vale para o **Buds Core**. Os outros modelos usam
outros plugins, que não foram analisados. **[INFERIDO]** Eles compartilham o framing e o CRC
(mesma família de UUID SPP, e o GalaxyBudsClient trata todos com o mesmo codec), mas os
IDs, payloads e offsets de status podem mudar. Não há garantia sem analisar o plugin
correspondente.

---

## 1. Transporte

| Item | Valor | Onde |
|---|---|---|
| Tipo | Bluetooth Classic, **RFCOMM** (`BluetoothDevice` → `BluetoothSocket`, `InputStream`/`OutputStream`) | `e8.G` (tag `Piano_SppConnectionManager`) |
| UUID do serviço usado | **`2e73a4ad-332d-41fc-90e2-16bef06523f2`** | `e8.G.<clinit>` (campo estático `i`) |
| UUID SPP padrão | `00001101-0000-1000-8000-00805F9B34FB`, presente no `<clinit>` mas **não guardado** (resultado descartado) | `e8.G.<clinit>` |
| BLE/GATT | Nenhum uso de GATT para controle no plugin. O `0000111E` (HFP) aparece só em `j7.i`, para estado de perfil. | grep sem ocorrências de `BluetoothGatt` no fluxo de controle |
| Recepção | Thread `e8.F` (`Piano_SppRecvThread`): lê o stream, acumula numa fila e separa os quadros | `e8.F.run` |
| Envio | `e8.G.e(msg)` → `msg.e()` (serialização) → handler de escrita | `e8.G.e` |

No Galaxy Wearable, `BluetoothUuidUtil.isSamsungBudsDevice()` considera "Buds Samsung"
qualquer aparelho que anuncie um destes UUIDs:

- `2e73a4ad-…` (`PROFILE_BUDS_BERRY`)
- `00001101-…` (`PROFILE_BUDS_STANDARD`)
- `00001102-…-00805f9b34fd` (`PROFILE_BUDS_FRIDAY`)

---

## 2. Formato do quadro

Codificação em `g8.a.e()`, decodificação em `g8.a.a(byte[])`, separação no stream em `e8.F.run`.

```
+------+---------+---------+-------+-----------------+--------+--------+------+
| SOM  | HDR lo  | HDR hi  | MsgID |  payload (N)    | CRC lo | CRC hi | EOM  |
| 0xFD |         |         |       |                 |        |        | 0xDD |
+------+---------+---------+-------+-----------------+--------+--------+------+
  [0]     [1]       [2]      [3]     [4 .. 3+N]       [4+N]    [5+N]    [6+N]
```

- **SOM** = `0xFD` (`bArr[0] = -3`); **EOM** = `0xDD` (`bArr[len+6] = -35`).
- **HDR** (16 bits, little-endian):
  - bits 0–9: `LEN = N + 3` (MsgID + payload + 2 bytes de CRC), mascarado com `& 0x3FF`.
  - bit 12 (`0x1000`): campo `c` de `g8.a`. É ligado pelo construtor `g8.a(id, true)`, usado
    nas **respostas** que o celular envia a mensagens iniciadas pelo fone (por exemplo o
    ack do `EXTENDED_STATUS_UPDATED`). **[INFERIDO]** Significa "is response": só aparece
    em respostas e em mensagens de OTA/HCM.
  - bit 13 (`0x2000`): campo `b` de `g8.a`. Só é ligado em blocos de dados de OTA/HCM
    (`D6.h`, `i8.e`). **[INFERIDO]** Significa "fragmento". Não é usado no EQ.
- **Tamanho total no fio** = `LEN + 4`. O separador `e8.F` lê `HDR & 0x3FF`, confere
  `fila[LEN+3] == 0xDD` e então extrai `LEN+4` bytes.
- **Multi-byte no payload:** little-endian (`ByteBuffer.order(LITTLE_ENDIAN)` em `g8.a.d()`).

### CRC

- Algoritmo: **CRC-16/XMODEM**, ou seja, polinômio `0x1021`, init `0x0000`, sem reflexão e
  sem XOR final. Tabela em `q7.d` (campo `a`, `table[1] = 4129 = 0x1021`), função `q7.d.b(len, buf)`.
- Verificação: a tabela extraída do APK é idêntica à gerada para CRC-16/XMODEM
  (`check("123456789") = 0x31C3`). Script em `docs/analise/frames.py` (código próprio; recebe como argumento o `q7/d.java` exportado).
- Cobertura: **MsgID + payload** (não inclui SOM, HDR nem EOM).
- Ordem no fio: **lo, hi**.
- Validação na recepção (`g8.a.a`): pega `bytes[3 .. fim-1]`, troca os dois últimos e calcula
  o CRC. O resultado deve ser **0** (propriedade do XMODEM com o CRC anexado em big-endian).
  Se falhar, o app registra `"createMsg() : CRC error !!!"` e descarta o quadro.

---

## 3. Equalizador

### 3.1 Presets

| Índice | Rótulo na UI (`EqualizerActivity.Y`) | Evento SA (`glide.c.O`) |
|---|---|---|
| 0 | `eq_preset_balanced` ("Normal") | `NORMAL` |
| 1 | `eq_preset_bass_boost` | `BASE_BOOST` |
| 2 | `eq_preset_smooth` ("Soft") | `SOFT` |
| 3 | `eq_preset_dynamic` | `DYNAMIC` |
| 4 | `eq_preset_clear` | `CLEAR` |
| 5 | `eq_preset_treble_boost` | `TREBLE_BOOST` |

`glide.c.O` lança `Exception("index error")` para índices fora de 0..5.

### 3.2 Definir preset

- Mensagem **`0x86`** (`-122`), chamada `EQUALIZER` no ack universal.
- Payload: **1 byte, índice do preset (0..5)**.
- Caminho no código: `EqualizerActivity` → clique (`A8.f`, case 2) → `com.bumptech.glide.c.O(idx)`
  → `Application.x.G(new g8.C((byte) idx, 2))`. O construtor `g8.C(b, 2)` chama
  `super((byte) -122)` e `b()` retorna `{idx}`.
- O mesmo envio acontece no Bixby Routine `piano_equalizer` (`Ca.c`, `hashCode 178417500`).
- Não há corpo de resposta específico. O fone pode mandar um **ack universal (0x42)** com
  `replyID = 0x86` e o valor aplicado (seção 6).

Exemplos de quadros completos (calculados pelo encoder reimplementado e conferidos pelo CRC):

| Preset | Quadro |
|---|---|
| 0 Normal | `FD 04 00 86 00 3E B1 DD` |
| 1 Bass boost | `FD 04 00 86 01 1F A1 DD` |
| 2 Soft | `FD 04 00 86 02 7C 91 DD` |
| 3 Dynamic | `FD 04 00 86 03 5D 81 DD` |
| 4 Clear | `FD 04 00 86 04 BA F1 DD` |
| 5 Treble boost | `FD 04 00 86 05 9B E1 DD` |

### 3.3 Ler o preset atual

- Byte **offset 9** do payload de `EXTENDED_STATUS_UPDATED (0x61)` (`g8.l`, campo `p`), copiado
  para `EarbudsInfo.r` (`t7.a.r`) em `g8.l.f()`. Essa é a variável que a `EqualizerActivity` lê.
- Também chega pelo ack universal `0x42` com `replyID = 0x86`: `T.f()` lê o byte em
  `payload[1]` e atualiza `EarbudsInfo.r` (`RedirectMsgSetEqualizerType`).
- **[INFERIDO]** Não existe mensagem de "consulta do EQ". O app não envia pedido de status:
  o fone **envia** o `0x61` sozinho após a conexão e o app só responde (seção 5). Nenhum envio
  de `0x61` sem a flag de resposta foi encontrado.

### 3.4 EQ customizado

- **Não existe EQ customizado no fone.** A tela tem 9 barras verticais, mas:
  - `EqualizerActivity.R()` só preenche as barras com curvas **fixas** por preset (tabela
    `{0,0,0,…}`, `{4,4,3,2,0,0,-1,0,-2}` etc., faixa visual −10..+10 com offset `+10`).
  - O listener das barras (`D8.v.onProgressChanged`) monta um `int[9]` e **não envia nada**.
- O "SoundCraft" (`SoundCraft*Activity`) é integração com Rotinas e com o app SoundCraft no
  celular (content provider `com.samsung.android.app.routines…`). Ele não manda bandas ao fone.
- `0x69` (`TWU_MSG_ID_EQUALIZER_SEND_DATA`) é enviado **sem payload** ao abrir
  `SoundEffectActivity`, e não há parser dedicado para uma resposta. **Função
  desconhecida.** Não será implementado.
- Valores das curvas visuais (só para exibição na UI):

| Preset | 9 bandas (dB visual) |
|---|---|
| 0 | 0 0 0 0 0 0 0 0 0 |
| 1 | 4 4 3 2 0 0 -1 0 -2 |
| 2 | 1 4 3 2 0 -1 -1 -2 -1 |
| 3 | 3 4 3 2 0 -1 -2 4 1 |
| 4 | -5 -3 -1 1 1 0 -1 4 2 |
| 5 | -5 -2 1 1 1 1 1 4 1 |

**[INFERIDO]** Essas curvas são ilustrativas. O código não as envia ao fone; o DSP do fone
aplica o preset pelo índice.

---

## 4. Controle de ruído (ANC / ambiente) e outros ajustes de áudio

### 4.1 Controle de ruído: essencial

- Mensagem **`0x78`** (`120`), chamada `NOISE_CONTROLS` no ack.
- Payload: **1 byte**.

| Valor | Modo | Evidência |
|---|---|---|
| 0 | Desligado | `a3.s.P(0)` → `N(0)` |
| 1 | ANC | `a3.s.Q()` → `N(1)` (exige fone no ouvido) |
| 2 | Ambiente | `a3.s.O()` → `N(2)` (log `"setAmbientSound fail…"`) |

- Envio: `a3.s.N(v)` → `G(new g8.C((byte) v, 0))`. O construtor no case default usa `super(120)`.
- Leitura: offset **12** do `0x61` (`noiseControls`), copiado para `EarbudsInfo.Z`.
- Restrição do app: ANC e ambiente só são aplicados se o fone estiver no ouvido
  (`u()`/`y()`/`h0`). **[INFERIDO]** É uma validação de UI; o firmware provavelmente aceita o
  comando mesmo assim. Testar no hardware.

| Modo | Quadro |
|---|---|
| Off | `FD 04 00 78 00 F0 81 DD` |
| ANC | `FD 04 00 78 01 D1 91 DD` |
| Ambiente | `FD 04 00 78 02 B2 A1 DD` |

### 4.2 Equilíbrio de som (balanço L/R): opcional

- **`0x8F`** (`-113`). Payload: 1 byte = progresso do `sound_balance_seekbar`, com
  `android:max="32"` em `activity_hearing_enhancements.xml`. Faixa 0..32.
- **[INFERIDO]** 16 é o centro (metade de 0..32).
- Envio em `HearingEnhancementsActivity` (`A4.q.h`). Leitura: offset 25 do `0x61` (`D` → `EarbudsInfo.b0`).
- Exemplo (centro): `FD 04 00 8F 10 97 19 DD`.

### 4.3 Bloqueio e controles de toque: opcional

- **`0x90`** `LOCK_TOUCHPAD` (`g8.r`). Payload de 7 bytes (0/1), nesta ordem:
  1. `touchControls`
  2. `tap`
  3. `doubleTap`
  4. `tripleTap`
  5. `touchAndHold`
  6. `callsDoubleTap`
  7. `callsTouchAndHold`
- **[INFERIDO]** 1 = gesto habilitado. A classe se chama `LOCK_TOUCHPAD`, mas o log do status
  rotula o 1º campo como `touchControls=`. A polaridade precisa ser confirmada no hardware.
- **`0x92`** `SET_TOUCHPAD_OPTION` (`g8.N`): `[opçãoEsq, opçãoDir]`. Os significados das opções
  não foram mapeados.
- **`0x79`** `SET_TOUCH_AND_HOLD_NOISE_CONTROLS` (`g8.M`): 6 bytes (0/1). O 1º trio é
  registrado como `NOISE_CONTROLS_MODE` e o 2º como `NOISE_CONTROLS_MODE_RIGHT`. A
  `TouchAndHoldActivity` envia `M(m0, n0, o0, W, X, Y)`, e esses campos vêm do offset 21 do `0x61`:
  bits 6,5,4 para o 1º trio e bits 2 (ANC), 1 (ambiente), 0 (off) para o 2º.
  **[INFERIDO]** O 1º trio é o lado esquerdo, na mesma ordem (ANC, ambiente, off). Concluo isso
  pela simetria com o rótulo `…_RIGHT` do 2º trio.

### 4.4 Outros setters de 1 byte (`g8.C(id, valor, 4, 0)`), fora do escopo de EQ

Todos foram identificados, mas **nenhum será implementado sem pedido**:

| ID | Nome (ack) / tela | Notas |
|---|---|---|
| `0x85` | `ADJUST_SOUND_SYNC` / GamingModeActivity | Modo jogo (latência) |
| `0x7A` | `SET_DETECT_CONVERSATIONS` | |
| `0x7B` | `SET_DETECT_CONVERSATIONS_DURATION` | |
| `0x96` | `EXTRA_HIGH_AMBIENT` | |
| `0x97` | `SET_VOICE_WAKE_UP` | Bixby |
| `0xAF` | `SET_SEAMLESS_CONNECTION` | |
| `0x6C` | InEarDetectionActivity | Detecção no ouvido |
| `0x9D` / `0xDA` | FitTest / EarAdaptation | Teste de ajuste |

`0x6A` (`g8.d`) é `[voiceBoost, volumeNormalization]`. Esses efeitos dependem do **SoundAlive
do celular Samsung** (`x5.a.R()/S()` exigem `n.H()` e a feature `voice_boost`/`volume_normalize`
do sistema). O processamento acontece no telefone, então **não faz sentido no Linux**.

### 4.5 Escritas perigosas: não implementar

Não implementar: FOTA/OTA (`h8.*`, `g8.O` …), coredump/log (`0x31`–`0x3B`), self-diagnostics
(`0xE8`–`0xED`), reset (`ACTION_MSG_ID_RESET`) e Find My Earbuds (`0xA0`/`0xA1`).

---

## 5. Mensagens recebidas (status)

### 5.1 `0x60` STATUS_UPDATED (`g8.P`, parser inline em `g8.a.a`)

| Offset | Campo | Notas |
|---|---|---|
| 0 | revision | |
| 1 | bateria esquerda (%) | |
| 2 | bateria direita (%) | |
| 3 | coupled (==1) | |
| 4 | (ignorado) | |
| 5 | placement: nibble alto = L, nibble baixo = R | 1 = no ouvido (`j = (nibble == 1)`); demais valores não mapeados |
| 6 | bateria do estojo | `101` → indisponível (`-1`) |
| 7 | *se a feature `CHARGING_STATUS`*: bit4 = L carregando, bit2 = R, bit0 = estojo | condicional à feature |
| 8, 9 | *se revision ≥ 2*: cradleLowBattery L/R | |

### 5.2 `0x61` EXTENDED_STATUS_UPDATED (`g8.l`)

O fone envia esta mensagem sozinho ao conectar. O app responde (`e8.m.C`):

1. `g8.k`: `0x61` com **flag de resposta** e payload `[0x00]`. Esse é o caminho padrão, porque a feature
   `SUPPORT_DIGITAL_ASSISTANT` é do celular. Quadro: `FD 04 10 61 00 1B 38 DD`.
2. `g8.z`: `0x88` com payload `[1, tipoTelefone, SDK_INT]`, onde `tipoTelefone` = 1 se Samsung e 2 caso contrário.
   **[INFERIDO]** É informação do host e é opcional. Para Linux, enviar `[1, 2, 34]` ou omitir;
   precisa de teste.

| Offset | Campo (nome do log / destino) |
|---|---|
| 0 | revision |
| 1 | (ignorado) |
| 2 | batteryLeft |
| 3 | batteryRight |
| 4 | coupled (==1) |
| 5 | (`EarbudsInfo.a`, significado não determinado) |
| 6 | placement L/R (nibbles) → wearingL/R |
| 7 | batteryCase (101 → indisponível) |
| 8 | adjustSoundSync (==1), ou seja, modo jogo |
| **9** | **equalizerType (0..5)** |
| 10 | flags de toque: b0 touchAndHold, b1 tripleTap, b2 doubleTap, b3 tap, b4 callsDoubleTap, b5 callsTouchAndHold, b7 touchControls |
| 11 | opção de toque longo: nibble alto = L, nibble baixo = R |
| **12** | **noiseControls (0 off / 1 ANC / 2 ambiente)** |
| 13 | voiceWakeUp (==1) (`EarbudsInfo.D`, usado pela `BixbyVoiceWakeUpActivity`) |
| 14–17 | dois `short` LE (`EarbudsInfo.A`, significado não determinado) |
| 18 | (ignorado) |
| 19 | seamlessConnection (**==0** → ligado) |
| 20 | (`EarbudsInfo.F`, significado não determinado) |
| 21 | modos alternados pelo toque longo: b0 off, b1 ambiente, b2 ANC (log `noiseControlsOff/Ambient/Anc`); b4–b6 = outro trio (ver `0x79`) |
| 22 | (`EarbudsInfo.a0`, significado não determinado) |
| 23–24 | (ignorados) |
| **25** | **soundBalance (0..32)** |
| 26+ | campos condicionais por revision/feature (spatial, voiceBoost, charging etc.) |

**[INFERIDO]** Os offsets 0–25 são lidos em sequência e sem condição na revisão atual do
parser. Campos depois do 25 dependem da revision e das features. O app Linux deve checar o
tamanho antes de ler cada campo.

---

## 6. `0x42` UNIVERSAL ACKNOWLEDGEMENT (`g8.T`)

- `payload[0]` = ID da mensagem confirmada (`replyID`).
- `payload[1..]` = eco do payload aplicado. Conferido em `g8.T.f`: o handler lê o valor a partir
  do byte 5 do quadro (= `payload[1]`) para `0x86` (EQ), `0x78` (ruído) e `0x90` (7 bytes de toque).
  **Não há** case para `0x8F` (balanço), então o balanço só é confirmado pelo próximo `0x61`.
- O fone também usa esta mensagem para avisar que **outro dispositivo** mudou uma configuração
  (classes `RedirectMsg*`).
- IDs com nome no handler, que usei para rotular a tabela:

| ID | Nome | ID | Nome |
|---|---|---|---|
| `0x78` | NOISE_CONTROLS | `0x90` | LOCK_TOUCHPAD |
| `0x79` | SET_TOUCH_AND_HOLD_NOISE_CONTROLS | `0x92` | SET_TOUCHPAD_OPTION |
| `0x7A` | SET_DETECT_CONVERSATIONS | `0x96` | EXTRA_HIGH_AMBIENT |
| `0x7B` | SET_DETECT_CONVERSATIONS_DURATION | `0x97` | SET_VOICE_WAKE_UP |
| `0x7C` | SET_SPATIAL_AUDIO | `0x98` | SET_NOISE_REDUCTION |
| `0x80` | SET_AMBIENT_MODE | `0x9F` | PASS_THROUGH |
| `0x83` | NOISE_REDUCTION_LEVEL | `0xA0`/`0xA1` | FIND_MY_EARBUDS_START/STOP |
| `0x84` | AMBIENT_SOUND_LEVEL | `0xA2` | MUTE_EARBUD |
| `0x85` | ADJUST_SOUND_SYNC | `0xAF` | SET_SEAMLESS_CONNECTION |
| **`0x86`** | **EQUALIZER** | `0x73` | AUTO_SWITCH_AUDIO_OUPUT |

---

## 7. Sequência de uso no Linux

1. Encontrar um aparelho pareado no BlueZ que anuncie o UUID `2e73a4ad-…`
   (`org.bluez.Device1.UUIDs`).
2. Abrir RFCOMM nesse serviço. O canal vem do SDP; usar o `ConnectProfile`/`Profile1` do BlueZ
   ou um socket RFCOMM com o canal descoberto.
3. Ler quadros. Ao receber `0x61`, guardar o estado e responder `FD 04 10 61 00 1B 38 DD`.
4. Para mudar o preset, enviar `0x86 [idx]`. A confirmação chega por `0x42` ou pelo próximo `0x60`/`0x61`.
5. **[INFERIDO]** `0x60` chega quando muda a bateria ou a posição dos fones. O app só trata o recebimento e nunca o solicita.

---

## 8. Essencial × opcional

| Prioridade | Função | Mensagens |
|---|---|---|
| **Essencial** | Presets de EQ (6) | `0x86` (set); `0x61` offset 9 e `0x42` (leitura) |
| **Essencial** | Estado / bateria L, R e estojo | `0x60`, `0x61` |
| **Essencial** | Handshake | resposta a `0x61` |
| Recomendado | ANC / ambiente / desligado | `0x78`; `0x61` offset 12 |
| Opcional | Balanço L/R | `0x8F`; `0x61` offset 25 |
| Opcional | Bloqueio de toques | `0x90`; `0x61` offset 10 |
| Fora | Voice boost / volume normalization | `0x6A` (DSP do celular) |
| Fora (sem pedido explícito) | FOTA, reset, diagnóstico, logs, Find My | — |

---

## 9. Evidências REA

Todas foram geradas com `rea-agents@6.3.0`, provider `jadx` 0.7.1 (JAR `6e5eacf5…`).
Limitação declarada pelo REA: *"Static decompiler observations do not establish runtime
behavior; the APK is never executed."*

| Evidence ID | APK | Classe.método | O que sustenta |
|---|---|---|---|
| `ev_df34ab88…c4f7a` | piano | `inspect_android_package` | pacote, versão, manifesto |
| `ev_2ec2c95e…45c8` | wearable | `inspect_android_package` | pacote, versão |
| `ev_ce450ef9…87f3` | piano | `e8.G.<clinit>` | UUID RFCOMM `2e73a4ad-…` |
| `ev_9eeda533…7bc8` | piano | `g8.a.e` | framing FD/HDR/CRC/DD |
| `ev_fea4e614…118a` | piano | `q7.d.b` | laço do CRC por tabela |
| `ev_8c2340e2…95ba0` | piano | `com.bumptech.glide.c.O` | envio do preset, índices 0..5 |
| `ev_bcc2bbea…b8477` | piano | `a3.s.N` | envio do controle de ruído |
| `ev_832cdf68…a47e` | piano | `e8.F.run` | separação de quadros no stream |
| `ev_99ec3ee6…107c` | piano | `g8.T.f` | nomes dos IDs no ack universal |
| `ev_ef2d3cd5…42e4ab` | wearable | `BluetoothUuidUtil.isSamsungBudsDevice` | detecção por UUID |
| `ev_02d93471…fc168` | wearable | `b7.l.a` | mapa nome → plugin |
| `ev_904d0cc2…f236` | piano | `g8.C.<init>(byte,int)` (overload 2) | `0x86` (case 2), `0x78` (default) |
| `ev_41feeb29…7289` | piano | `g8.l.f` | campos do `0x61` → `EarbudsInfo` |
| `ev_6af152dd…2f97` | piano | `g8.r.b` | payload de 7 bytes do `0x90` |
| `ev_952e8563…a56e` | piano | `a3.s.P` | valores 0/1/2 do controle de ruído |
| `ev_cbbfe96a…bb41` | piano | `g8.k.<init>` | resposta ao `0x61` (flag de resposta) |
| `ev_c08c8c27…c4fe` | piano | `g8.a.a` | parser: validação do CRC, `0x60`, despacho por ID |

### 9.1 Limitações das evidências

- `q7.d.<clinit>` (tabela do CRC) voltou do REA como `body_status: not_available`, porque o JADX
  inlina o inicializador na declaração do campo. A tabela foi lida do export JADX e validada
  contra o CRC-16/XMODEM calculado de forma independente. O laço que usa a tabela (`q7.d.b`)
  tem evidência REA.
- Os offsets de `0x61` acima do 25, o significado dos nibbles de placement diferentes de 1 e as
  opções de `0x92` não foram mapeados.
- Referências recebidas por reflexão ou carregamento dinâmico ficam desconhecidas. Isso é
  uma limitação padrão do REA.

---

## 10. Referência externa (só para conferência)

O GalaxyBudsClient (timschneeb) tem `BudsCoreDeviceSpec`, com `ServiceUuid = Uuids.SppNew`,
`SOM`/`EOM` padrão e as features `NoiseControl`, `Anc`, `AmbientSound`, `AdvancedTouchLock` e
`StereoPan`, entre outras. Isso é **coerente** com esta análise. Nenhum byte deste documento
foi tirado de lá.

---

## 11. Confirmado com o hardware (SM-R410, 2026-10-14)

Testado com o `fone-eq --debug` via BlueZ `Profile1` + `ConnectProfile`, com os dois fones no ouvido.

| Item | Resultado |
|---|---|
| Transporte | O BlueZ resolveu o canal RFCOMM pelo UUID `2e73a4ad-…f2` sem configuração extra |
| `0x61` espontâneo | Chega logo após conectar; a resposta `FD 04 10 61 00 1B 38 DD` é aceita. `0x88` não foi necessário |
| Status real | `00 0A 64 64 01 00 11 FF 00 00 BF 22 02 … 10 …` (56 bytes): bateria 100/100, no ouvido, EQ 0, ambiente, balanço 16 |
| Estojo fora de alcance | Byte 7 = `0xFF` (255), não `101`. O app trata qualquer valor > 100 como indisponível |
| Toques | Byte 10 = `0xBF` com os gestos no padrão de fábrica. Reforça que 1 = gesto ativo, mas ainda falta testar a escrita do `0x90` |
| Balanço | 16 por padrão, o que reforça que 16 é o centro |
| EQ `0x86` | `FD 04 00 86 01 1F A1 DD` → ack `0x42 [86 01]`; persiste no fone (o `0x61` seguinte trouxe EQ = 1) |
| Ruído `0x78` | ANC (`01`) e ambiente (`02`) → ack `0x42 [78 xx]` |
| Flag do ack | O `0x42` vem com o bit `0x1000` ligado. A flag marca respostas nos dois sentidos |
| Após um comando | O fone também manda `0x60`, `0x68`, `0x41`, `0xCD` e `0x47` (versão, modelo `R410…` etc.); o app os ignora |

---

## 12. Mapeamento completo para o app final (Fase 2)

Fonte: export JADX do `pianomgr` 8.5.26070351 (mesmo método da seção 0). Os nomes de classe são
os do DEX. "Ack no SM-R410" = `0x42` observado no fone real em 2026-10-14 (firmware R410XXU0AYI2).

### 12.1 Features do Buds Core (`h7.e.a` + `g8.l`)

O plugin parte de um conjunto fixo (`h7.e.a`, usado por `h7.d.<init>(e)`):
`AMBIENT_SOUND`, `ANC`, `AMBIENT_DURING_CALLS`, `TOUCH_CONTROL_FOR_CALLS`, `IN_EAR_DETECTION`,
`EARBUD_FIT_TEST`, `CUSTOMIZED_AMBIENT_SOUND`, `ANC_WITH_ONE_EARBUD`, `RING_ON_WEARING`,
`CHARGING_STATUS`, `OFFLINE_FINDING`, `BIXBY_VOICE_WAKEUP`, `BACKGROUND_AUTO_FOTA`,
`AUTOMATIC_UPDATES_AGREE`, `DELETED_CHARGING_CONDITION_IN_INTEGRATED_BATTERY`.

Ao receber o `0x61`, `g8.l` acrescenta `SELF_DIAGNOSTIC` (revision ≥ 0) e só acrescentaria
`AUTO_PAUSE_RESUME` com revision ≥ 9999, o que um byte nunca alcança. Logo **o Core não tem
pausa automática**, nem `_360_AUDIO`, `SOUND_DETECT`, `EAR_ADAPTATION`, `SEAMLESS_CONNECTION` ou
`HEARING_ENHANCEMENT` (que aparecem em telas compartilhadas do plugin, mas ficam ocultas).

### 12.2 Mensagens enviadas

| ID | Função | Payload | Classe / tela | Ack no SM-R410 |
|---|---|---|---|---|
| `0x29` | pedir números de série | vazio | `g8.j()` (em `e8.m`, ao mudar "coupled") | resposta `0x29` com flag |
| `0x6E` | detecção no ouvido p/ chamadas | `[1 = desligado]` (invertido) | `D8.c` case 3, `AdvancedFeatureActivity` | sim |
| `0x6F` | controle de ruído com um fone | `[0/1]` | `g8.E` | sim |
| `0x79` | ciclo do "tocar e segurar" | 6 bytes `[ANC, amb, off]×2` | `g8.M` (`TouchAndHoldActivity`) | sim |
| `0x82` | som ambiente personalizado | `[on, volE, volD, tom, conversationBoost, NR]` | `g8.g` | **não** |
| `0x85` | modo de jogo | `[0/1]` | `D8.c` case 2 (`GamingModeActivity`, Labs) | sim |
| `0x8B` | som ambiente durante chamadas | `[0/1]` | `D8.c` case 0 | sim |
| `0x8F` | balanço | `[0..32]` | `A4.q` | **sim** (sem case em `g8.T.f`) |
| `0x90` | travar toque / gestos | 7 bytes | `g8.r` | sim |
| `0x92` | ação do "tocar e segurar" | `[esq, dir]` | `g8.N` | sim |
| `0x96` | volume extra-alto do ambiente | `[0/1]` + `0x82` com volume 4 | `h7.d` / `EnhancementAmbientVolumeActivity` (Labs) | **não** |
| `0x9D` | teste de encaixe | `[1 iniciar / 0 parar]` | `FitTestActivity.V` | — |
| `0xA6` | Encontrar fones (Core) | vazio | `K7.b.b` (`0xA0` se não houver `RING_ON_WEARING`) | sim |
| `0xA1` | parar Encontrar fones | vazio | `K7.b.c` | sim |
| `0xA2` | silenciar fone na busca | `[esq, dir]` | `K7.b.d` (`g8.d(-94)`) | não |
| resposta | `0x60`, `0x63`, `0x68` (e `0x61`) | `[0x00]` + flag `0x1000` | `e8.m` (`new C(id, 0, 0)`) | o fone confirma o `0x68` com `0x42 [68 00]` |

Opções do `0x92` (`TouchAndHoldActivity.W`): 1 assistente de voz, 2 alternar controle de ruído,
3 volume (esquerdo abaixa, direito aumenta), 4 intérprete, 5 mindfulness, 6 Spotify, 7+ outros
apps. 1 e 4–7 dependem de apps do celular. As mensagens `settings_touchpad_option_toast_*` mostram
que **volume é sempre usado nos dois lados**: escolher volume num lado muda o outro, e sair de
volume num lado leva o outro junto.

Volume do som ambiente: `EnhancementAmbientVolumeActivity.R` limita cada lado a 0..2 e usa 4 para
o "extra-alto". **[INFERIDO]** Como o Core não lê o estado do extra-alto no `0x61` (feature
`EXTRA_HEARING_ENHANCEMENT_LV5` ausente), o app deduz "extra-alto ligado" quando o volume é 4.

Teste de encaixe: só com os dois fones no ouvido (`FitTestActivity.U`). O resultado chega em
`0x9E [esq, dir]`: 1 = bom encaixe (`f14172S`), 2 = barulho demais (`f14173T`), outro = ruim.
Depois do resultado o app envia `0x9D [0]`.

Encontrar fones: o plugin para sozinho após 180 s (`K7.b.b`, `postDelayed(…, 180000)`). O aviso
do app original (`play_sound_dialog_desc`) diz que o som aumenta aos poucos e pode causar dano
auditivo se os fones estiverem no ouvido.

### 12.3 Mensagens recebidas

| ID | Conteúdo | Classe |
|---|---|---|
| `0x60` | ver §5.1; com `CHARGING_STATUS` o byte 7 traz carga (bit4 E, bit2 D, bit0 estojo) | `g8.a.a` case 96 |
| `0x61` | ver §5.2 e o complemento abaixo | `g8.l` |
| `0x68` | `[hwE, hwD, swE[20], swD[20], touchE, touchD]` | `g8.b0` (no `g8.a.a`) |
| `0x29` | `serialE[11], serialD[11]` (ASCII) | `g8.j` |
| `0xCD` | 9 bytes + 11 bytes do estojo | `g8.f` |
| `0x77` | `[ruído, wearing]` quando o fone muda o modo sozinho | `g8.D`, `e8.l` |
| `0x9E` | resultado do teste de encaixe `[esq, dir]` | `g8.e` |

**[INFERIDO]** No `0xCD`, o log do APK chama os 11 bytes de `serialNumber` e os 9 de
`swVersion`, mas grava o primeiro campo em `case_serial_number_pref_key`. O app segue o log: no
SM-R410 os 11 bytes têm o formato de número de série Samsung.

No SM-R410, ao trocar para ambiente, o fone mandou `0x77 [00]` (só 1 byte) antes do ack
`0x42 [78 02]`. O app faz como o APK (aplica o `0x77` e depois o ack), e o estado final fica certo.

Outras mensagens vistas no SM-R410 e não usadas: `0x41`, `0x47` (com flag de resposta).

### 12.4 `0x61` completo no Core (offsets 26 em diante)

A leitura segue a ordem de `g8.l`, com os blocos condicionais do Core:

| Offset | Campo (`g8.l` → `EarbudsInfo`) | Uso no app |
|---|---|---|
| 5 | `f16254i` → `a`: fone primário (1 = esquerdo) | info |
| 11 | nibbles: opção do "tocar e segurar" E/D | `0x92` |
| 21 | bits 6,5,4 = 1º trio; 2,1,0 = 2º trio (ANC, ambiente, off) | `0x79` |
| 26 | `voiceDetect` | não usado (sem tela no Core) |
| 27 | `voiceDetectDuration` | não usado |
| 28 | `f21056h0`: ruído com um fone | `0x6F` |
| 29 | `customizeSoundOn` | `0x82` |
| 30 | nibbles: volume do ambiente E/D | `0x82` |
| 31 | `f21062l0`: tom do ambiente | repassado no `0x82` |
| 32 | `doubleTapSide` (sem a feature) | ignorado |
| 33 | `f21007B`: ambiente durante chamadas | `0x8B` |
| 34 | (com `IN_EAR_DETECTION`) `0` = detecção ligada | `0x6E` |
| 35 | `spatialAudio` | ignorado |
| 36 | `conversationBoost` | repassado no `0x82` |
| 37 | `customizeNoiseReductionLevel` | repassado no `0x82` |
| 38–40 | neck stretch, bixbyKeyword, hearingTestValue | ignorados |
| 41 | (ignorado pelo APK) | — |
| 42 | `spatialAudioHeadTracking` | ignorado |
| 43 | (com `CHARGING_STATUS`) carga: bit4 E, bit2 D, bit0 estojo | bateria |

Conferido com o `0x61` real do §11: 28 = 0, 29 = 1, 30 = `0x11`, 31 = 2, 33 = 0, 34 = 0
(detecção ligada), 36 = 1, 37 = 1, 43 = 0.

### 12.5 Modelos

Os nomes vêm de `b7.l.a` (Galaxy Wearable). Só o plugin do Core foi analisado. Os demais modelos
com formato `0xFD` ficam como **experimentais**, com bateria (offsets 2/3 do `0x61`), presets
(`0x86`) e, quando têm ANC, ruído (`0x78`). **[INFERIDO]** Isso supõe que esses IDs e offsets
são iguais nos outros plugins, o que não foi verificado. O Galaxy Buds original (2019,
`fridaymgr`) usa outro formato de quadro e aparece como não suportado.

# Referência de design: Galaxy Wearable + plugin do Buds Core

Mapeamento da interface do app original, para que o Buds Studio tenha a mesma organização.
Serve **só de referência**: nenhuma imagem, ícone, animação, fonte (SamsungOne) ou marca foi copiada.

**Fontes:**
- APK `com.samsung.accessory.pianomgr` 8.5.26070351.
- Galaxy Wearable 2.2.72.26092361.
- REA (CLI `search-android-classes`, Evidence `ev_6a1dc5ce1afbdca857732c566fdf0560ab2383abcaeebcdd7300d90c9a41a037`): lista as classes de `module.home`, incluindo os cartões `CardNoiseControls`, `CardMenuControl`, `CardMenuFeatures`, `CardAccessibility`, `CardMenuOtherApps`, `CardMenuEarbuds` e a gaveta `NavigationDrawer`.
- Layouts (`res/layout`), strings (`res/values`, `res/values-pt-rBR`), cores (`values`, `values-night`) e dimensões: lidos no export do JADX feito com o JAR do REA. O REA não decodifica recursos.

## 1. Navegação

```
Gaveta de aparelhos (NavigationDrawer)        Tela inicial (HomeOneUI8xActivity)
 ├─ lista de aparelhos (nome, "Conectado", ✓)   ├─ cabeçalho: imagem do fone, nome, bateria E/D/base
 ├─ Adicionar novo aparelho                     ├─ controle de ruído segmentado
 └─ Remover aparelhos                           ├─ cartão: Qualidade e efeitos sonoros ▸ / Controles de toque [chave] ▸
                                                ├─ cartão: Gerenciar conexões ▸ / Recursos avançados ▸
Menu do topo: Pesquisar, Configurações          ├─ cartão: Acessibilidade ▸
                                                ├─ cartão: Buscar meus fones ▸ / Diagnóstico ▸ / Auracast ▸
                                                └─ cartão: Atualiz. de software ▸ / Dicas e manual ▸ / Sobre os fones ▸
```

Cada item ▸ abre uma subtela com botão de voltar no topo (Activity própria).

## 2. Telas, ordem dos itens e tipo de controle

O nome aparece em inglês / pt-BR, exatamente como no APK.

### Tela inicial (`activity_home_one_ui_8`, `home_image_area`)
| Ordem | Item | Controle |
|---|---|---|
| 1 | nome do fone ("Galaxy Buds Core") + "Disconnected / Desconectado" | texto |
| 2 | bateria: Left / Esquerdo, Right / Direito, Case / Base carregadora | barra circular + % |
| 3 | controle de ruído (`card_noise_control_oneui8x`): **Off / Desativado · Ambient sound / Som ambiente · Active noise canceling / Cancelamento de ruído ativo** (da esquerda para a direita) | controle segmentado |
| 4 | Sound quality and effects / Qualidade e efeitos sonoros | linha ▸ |
| 5 | Touch controls / Controles de toque | linha ▸ com chave |
| 6 | Manage connections / Gerenciar conexões | linha ▸ |
| 7 | Advanced features / Recursos avançados | linha ▸ |
| 8 | Accessibility / Acessibilidade | linha ▸ |
| 9 | Find My earbuds / Buscar meus fones de ouvido | linha ▸ |
| 10 | Diagnostics / Diagnóstico | linha ▸ (autodiagnóstico) |
| 11 | Listen to Auracast broadcast / Ouvir a transmissão do Auracast | linha ▸ |
| 12 | Earbuds software update / Atualiz. de software dos fones | linha ▸ |
| 13 | Tips and user manual / Dicas e manual do usuário | linha ▸ |
| 14 | About earbuds / Sobre os fones de ouvido | linha ▸ |

### Qualidade e efeitos sonoros (`activity_sound_effect`)
| Item | Controle |
|---|---|
| Equalizer / Equalizador (abre a lista de presets) | linha ▸ |
| Boost dialogue / Realçar diálogo | chave (processado no celular) |
| Loudness normalization / Normalização de volume | chave (processado no celular) |
| Earbud fit test / Teste de ajuste de fones de ouvido | cartão separado |

Presets (`EqualizerActivity`): Balanced / Equilibrado, Bass boost / Mais graves, Smooth / Suave,
Dynamic / Dinâmico, Clear / Nítido, Treble boost / Mais agudos. Controle: lista de opção única.

### Controles de toque (`activity_touch_controls`)
| Item | Controle |
|---|---|
| barra liga/desliga (Touch controls / Controles de toque) | chave em barra |
| **Media controls / Controles de mídia** | cabeçalho |
| Play or pause track / Reproduz ou pausa a faixa — Tap / Tocar | chave |
| Play next track / Reproduz a próxima faixa — Double tap / Toque duplo | chave |
| Play previous track / Reproduz a faixa anterior — Triple tap / Toque triplo | chave |
| Touch and hold / Manter pressionado — "Left: %s / Esquerda: %s", "Right: %s / Direita: %s" | linha ▸ com chave |
| **Call controls / Controles de chamada** | cabeçalho |
| Answer call or end call / Atender ou encerrar chamada — Double tap / Toque duplo | chave |
| Decline call / Recusar chamada — Touch and hold / Manter pressionado | chave |

Manter pressionado (`activity_touch_and_hold`): listas Left / Esquerdo e Right / Direito com opção
única: Switch noise controls / Alternar controles de ruído, Volume down / Diminuir volume (esq.),
Volume up / Aumentar volume (dir.) e opções de apps do celular.

### Gerenciar conexões (`activity_connections`)
Calls / Chamadas e Audio / Áudio (chaves dos perfis Bluetooth), Seamless earbud connection /
Conexão direta de fones de ouvido, Auto switch Buds, Reset. Não há protocolo do fone para nenhum
desses itens; são ajustes de Bluetooth/conta do celular.

### Recursos avançados (`activity_advanced_features`)
| Item | Controle |
|---|---|
| Read notifications aloud / Ler em voz alta as notificações | linha ▸ (celular) |
| Use Ambient sound during calls / Usar Som amb. durante chamadas | chave com descrição |
| In-ear detection for calls / Detecção de fone de ouvido para chamadas | chave com descrição |
| Labs | linha ▸ (cartão separado) |

### Labs (`activity_labs`)
"Check out these experimental features. / Confira estes recursos experimentais." → Gaming mode /
Modo de jogo (chave), Extra-clear call sound / Refinar o som da chamada (chave; sem a feature no
Core), Hearing enhancements / Melhorias de audição (linha ▸), Extra-high ambient volume / Volume
ambiente extra-alto (`EnhancementAmbientVolumeActivity`, chave).

### Acessibilidade / Melhorias de audição (`activity_hearing_enhancements`)
Left/right sound balance / Balanço de som da esq/dir (slider com marca no centro, Left/Esquerdo e
Right/Direito nas pontas) e Noise controls with one earbud / Controles de ruído com um fone (chave).

### Buscar meus fones (`activity_find_my_earbud`)
Texto "Your earbuds will start beeping when you tap Start." / "Seus fones de ouvido começarão a
emitir um sinal sonoro quando você tocar em Iniciar.", estado de cada lado, silenciar esquerdo e
direito, botão Start / Iniciar.

### Sobre os fones de ouvido (`activity_about_earbuds`)
Nome do aparelho + Rename / Renomear, Product name / Nome do produto, Model number / Núm. modelo,
Serial number / Número de série (direito, esquerdo, Case / Base carregadora), Software information
/ Informações do software, Battery information / Informações da bateria, Legal information /
Informações legais e o bloco "Looking for something else?" (Software update, Reset, Contact us).

## 3. Correções ao mapa sugerido

| Mapa sugerido | APK |
|---|---|
| "Controles/Toque" | **Controles de toque**, com chave liga/desliga na própria linha |
| "Encontrar meus fones" | **Buscar meus fones de ouvido** |
| "Configurações do fone" | Não existe. Os ajustes ficam em **Recursos avançados** e **Acessibilidade** |
| "Labs" na tela inicial | Labs fica **dentro de Recursos avançados** |
| "Sobre os fones" | **Sobre os fones de ouvido** |
| — | Há também **Gerenciar conexões**, **Acessibilidade** e o bloco de Diagnóstico/Auracast |
| ordem do segmentado | **Desativado · Som ambiente · Cancelamento de ruído ativo** |

## 4. Paleta, cantos e espaçamentos (referência)

| Token (APK) | Claro | Escuro |
|---|---|---|
| `color_primary` | `#387AFF` | `#387AFF` |
| `color_background` | `#F1F1F3` | `#010102` |
| `main_info_card_background` (cartões) | `#FCFCFF` | `#17171A` |
| `color_text_primary` | `#010102` | `#FCFCFF` |
| `basic_token_sys_surface_container` | `#E4E4E7` | `#3A3A3D` |
| `basic_token_sys_outline` / divisórias | `#CCCCCE` | `#636368` |
| `color_noise_controls_progress_tint_color` | `#EDEDED` | `#3E3E3E` |
| `color_battery_background` | `#E9E9E9` | `#252525` |

Cantos: `rounded_corner` / `sesl_rounded_corner_radius` = 26dp; `shape_corner_radius_large` =
32dp; `shape_corner_radius_small` = 12dp; diálogos 26dp; botões 18dp.
Espaçamentos: `list_item_text_top_bottom_padding` = 14dp; `sesl_list_item_padding_horizontal` = 12dp.

Esses valores estão em `data/style.css` como variáveis (`--bs-*`), com versão clara e escura.

## 5. Como cada tela virou uma tela do Buds Studio

| App original | Buds Studio | Observação |
|---|---|---|
| Gaveta de aparelhos | Barra lateral (janela larga) e seletor no título (janela estreita) | + bateria e status de cada fone |
| Adicionar novo aparelho / Remover aparelhos | Mesmos nomes; adiciona dos pareados no BlueZ; remover só tira do app | não despareia |
| Tela inicial: cabeçalho + bateria | Cartão de cabeçalho com ilustração própria e as três baterias | |
| Controle de ruído segmentado | `AdwToggleGroup` com a mesma ordem | |
| Qualidade e efeitos sonoros | Subtela: Equalizador ▸, **Equalizador do computador ▸** (extra), Teste de ajuste | Realçar diálogo e Normalização ficam ocultos (celular) |
| Equalizador | Subtela com a lista de presets | |
| Controles de toque (+ Manter pressionado) | Subtelas iguais; ciclo de modos de ruído dentro de Manter pressionado | |
| Gerenciar conexões | Subtela com conexão do app (conectar, reconectar) | Chamadas/Áudio/Seamless ocultos (sem protocolo) |
| Recursos avançados → Labs | Subtela e sub-subtela iguais | Refinar o som da chamada oculto (sem a feature) |
| Acessibilidade | Subtela com balanço, controles de ruído com um fone e volume do som ambiente | |
| Buscar meus fones de ouvido | Subtela com Iniciar/Parar e silenciar lados | |
| Diagnóstico (autodiagnóstico), Auracast, Atualização de software, Dicas | Ocultos | escrita de manutenção / sem suporte |
| Sobre os fones de ouvido | Subtela com nome, modelo, firmware, números de série e endereço | |
| Configurações (menu do topo) | Menu → Configurações (inclui o Tema) | |
| — | **Recursos do Linux** (cartão próprio, depois dos originais): Áudio Bluetooth, Perfis, Diagnóstico (pacotes) | extras |

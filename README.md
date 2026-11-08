# fitelnet-toolkit

FITELnet **F221（無印）** を Claude Code / Codex 等から運用するスキルとSSHクライアント、公式PDFを手元で検索するツールです。
[yuu61/ix-toolkit](https://github.com/yuu61/ix-toolkit) の設計とPythonコードを基に、F221のCLIに対応させています。

## インストール

Python 3.10以上。展開したフォルダで実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\fitelnet-ssh --help
.\.venv\Scripts\fitelnet-manual --help
```

以降の例のコマンドは `.venv` を有効にするか、上のようにフルパスで実行してください。
uvがある場合は `uv tool install -e .` でもインストールできます。
スキルは `skills/fitelnet-ssh/SKILL.md` と `skills/fitelnet-manual/SKILL.md` です。
エージェントのスキル配置先からこの2フォルダを参照できるようにし、`fitelnet-ssh` と `fitelnet-manual` をPATHに置きます。
スキルだけのコピーではPythonコマンドはインストールされません。本体フォルダも残してください。

## 接続先

`~/.fitelnet-toolkit/devices.json`、または `--inventory PATH` で指定します。
`examples/devices.example.json` を編集し、秘密を含む実ファイルはリポジトリに置かないでください。

```json
{"devices":{"branch":{"host":"192.0.2.1","username":"admin","model":"F221","password_env":"BRANCH_PASSWORD"}}}
```

```powershell
$env:BRANCH_PASSWORD = Read-Host 'SSH password' -MaskInput
$env:FITELNET_ENABLE_PASSWORD = Read-Host 'enable 15 password (必要な場合)' -MaskInput
fitelnet-ssh --list
fitelnet-ssh -d branch "show version" "show lte-module status"
```

`Read-Host -MaskInput` は PowerShell 7.1以上用です。旧PowerShellでは対話用の `--ask-password` を使うか、環境変数を秘密管理ツールから設定してください。
インベントリは本人だけが読める権限が必要です。権限不足時はCLIが修正方法を表示します。
SSHの鍵認証、`~/.ssh/config` の別名・Include・ProxyJumpに対応します。ProxyCommandは未対応です。
未登録ホスト鍵は接続中に受け入れます（自動的な永続登録はしません）。既知の鍵と不一致なら拒否します。
元ツールの接続方針を踏襲しているため、初回接続先は別途確認してください。

## F221の設定モデル

| 操作 | 対象 | CLI |
| --- | --- | --- |
| 状態確認 | 稼働中設定 | `show running.cfg` |
| 編集 | working.cfg（候補設定） | `--config-file change.conf` |
| 反映 | 候補設定を動作に反映 | `--commit`（`commit moff`） |
| 保存 | 候補設定を起動設定に保存 | `--save`（`save moff`） |

`--config-file` **だけでは反映・保存しません**。`--save` だけでは動作に反映しません。
`--commit --save` は反映後に保存します。反映が失敗した場合、保存は送りません。
saveは稼働中設定ではなく **working.cfg全体** を保存します。他の作業者の未反映編集も含まれ得ます。
commitもworking.cfg全体を反映します。事前に `show working.cfg` と `show running.cfg` を比較してください。

```powershell
fitelnet-ssh -d branch --backup
fitelnet-ssh -d branch "show working.cfg" "show running.cfg" "show startup-config"
fitelnet-ssh -d branch --config-file change.conf
fitelnet-ssh -d branch "show working.cfg"
fitelnet-ssh -d branch --commit
fitelnet-ssh -d branch "show running.cfg" "show ip route"
fitelnet-ssh -d branch --save
```

`--backup` は変更前のrunning.cfgをUTF-8ファイルに退避します。バックアップは秘密情報を含み得ます。
一度の実行では show → backup → config → commit → save の順です。反映後のshowは別の呼び出しで実施してください。
設定ファイルは1行1コマンド、空行・`#`・`!` のコメント行は無視します。
サブモードから戻る `exit` と `end` は利用できますが、最後の設定行より前に特権モードへ戻ると処理を止めます。
設定ファイルへcommit/save等の運用コマンド、対話入力、制御文字、パイプは入れられません。
証明書・鍵生成・バナー等の対話操作、再起動、SIM切替・LTE接続/切断の自動化は対象外です。
設定エラーで後続処理を停止します。候補設定の部分編集は自動で取り消しません。
タイムアウトや切断時は結果が不明なため、再接続して状態を確認し、自動再試行しないでください。
設定応答本文は `--raw` でも表示しません。show本文とバックアップにはこの保護は適用されません。

## 公式マニュアル

```powershell
fitelnet-manual build
fitelnet-manual search "show lte-module status" --doc operation
fitelnet-manual search "sim-profile" --doc config --json
fitelnet-manual page operation 84
```

初回buildは7冊をダウンロードし、PDFページ単位のMarkdownと索引を作ります。ネット接続なしで検索できます。
対象冊子は `src/fitelnet_manual/manifest.json` に定義しています。定期取得はしません。
既存PDFは再利用します。更新するときだけ `build --force` を指定してください。
手元のPDFを使う場合は `build --pdf-dir PATH`（manifestと同じファイル名）を指定します。
`--doc operation` のように対象を絞れます。
保存先は `--root PATH` → `FITELNET_MANUALS` → `~/.fitelnet-toolkit/manuals` の順です。
`--root` はサブコマンドの前に置きます。例: `fitelnet-manual --root ./manuals build --doc operation`。
各ページに原本URL・PDFページ番号・SHA-256を残します。表紙を1とするページ番号で、冊子の印刷番号と異なる場合があります。
PDF本文・変換結果は古河電工の著作物です。各自の手元で取得し、配布物には含めません。
図表の構造復元・OCR・ページ画像生成は行いません。表の列、図、適用機種・ファームウェア条件はリンク先の原本を確認してください。
F220/F221共通冊子に他機種の説明が含まれることがあります。F221 EXをF221と同一扱いしないでください。

## 検証と範囲

ローカルの模擬F221 SSHサーバーで、接続・表示・候補編集・commit/save・失敗時停止を検証します。
**実機F221への接続試験は未実施です。** 初回はshow/バックアップから確認してください。
機種名だけの置換ではなく、NEC専用SSHドライバーをF221用に置き換えています。
Go製manualbookは引き継がず、F221のPDFに絞ったPythonツールを実装しています。

```powershell
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -t .
ruff check src tests
ruff format --check src tests
```

参照: [公式マニュアル一覧](https://www.furukawaelectric.com/fitelnet/product/f220/manual/)、
[運用管理編](https://www.furukawaelectric.com/fitelnet/f/man/220/pdf/cmd_refe_ope.pdf)（configure terminal / end / commit / save / no more）、
[構成定義編](https://www.furukawaelectric.com/fitelnet/f/man/220/pdf/cmd_refe_config.pdf)。
2026-11-04に掲載URLを確認。資料の改訂と実機ファームウェアの対応は使用時に確認してください。

MIT。元コードの著作権表示はLICENSEに維持し、変更範囲はNOTICE.mdに記載しています。

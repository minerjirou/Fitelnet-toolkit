---
name: fitelnet-ssh
description: FITELnet F221のSSH状態確認、バックアップ、候補設定編集、commitによる反映、saveによる永続化を行う。NEC IXやF221 EXには適用しない。
---

# FITELnet F221 operations

ユーザーの依頼から対象と操作を決める。PATHの `fitelnet-ssh` を使用する。
接続先は `fitelnet-ssh --list` で調べる。インベントリ既定値は `~/.fitelnet-toolkit/devices.json`。
接続情報や秘密は会話に貼らず、インベントリの `password_env` や鍵認証を使う。
`>` からの昇格には `FITELNET_ENABLE_PASSWORD` または `--enable-password-env VAR` が必要。

最初に `show version` を確認し、無印F221と実機のファームウェアを把握する。
コマンド構文・対応バージョンが不明なら fitelnet-manual で公式資料を確認する。
NECの `enable-config`、`svintr-config`、`write memory` は使わない。

読み取り依頼はshowまたはバックアップまで。showは特権モードで実行し、設定モードには入らない。
LTEの状態確認は `show lte-module status`。SIM切替やLTEリセットを読み取り依頼から追加しない。
showとバックアップは秘密を含み得るので、報告には必要な情報だけを抜粋する。

変更には [references/configure.md](references/configure.md) を読む。
確認が必要な場合は対象・具体的な設定行・反映と保存の有無を提示する。既存の承認を尊重し、同じ承認を繰り返し求めない。
作成・開発だけの依頼は実機への投入を意味しない。

```text
fitelnet-ssh -d branch "show version" "show lte-module status"
fitelnet-ssh -d branch --backup
fitelnet-ssh -d branch "show running.cfg" "show working.cfg" "show startup-config"
```

一度の呼び出しはshow→backup→config→commit→save。反映後の検証showは別の呼び出しで行う。
実機接続試験は未実施のため、初回はshowで接続を確認する。

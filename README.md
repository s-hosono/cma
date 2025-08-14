# CMA プロトタイプ

最小構成のWebプロトタイプ。図面アップロード→簡易特徴抽出→工程分解→企業マッチング→レポート生成の一連を体験できます（ルール/ダミー実装）。

## 起動

```
# 依存インストール
pip install -r requirements.txt
# サーバ起動
python -m app
```

## 機能
- 図面/仕様PDF/画像のアップロード
- 簡易OCR（pytesseract任意）とメタ推定（拡張子/ファイル名）
- ルールベース工程分解
- サンプル企業DBに対するルール/NLP風スコアリング
- HTMLレポート生成＋Word(.docx)ダウンロード

## 注意
- 学術/PoC目的のダミー実装です。セキュリティ、精度、モデルは最小限。

## 依存
`python-docx` を使用して Word(.docx) を生成します。`pip install -r requirements.txt` で自動インストールされます。

## LLM設定（任意）
- 環境変数で設定します：
	- OPENAI_API_KEY: APIキー
	- OPENAI_BASE_URL: OpenAI互換エンドポイントURL（任意）
	- OPENAI_MODEL: 例 gpt-4o-mini / gpt-4o / o4-mini 等（任意）
- 未設定でも動作します（ルールベースにフォールバック）。

### Azure OpenAI の場合（推奨）
```
export AZURE_OPENAI_API_KEY=***
export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
export AZURE_OPENAI_API_VERSION=2024-12-01-preview
export AZURE_OPENAI_DEPLOYMENT=o1
```

### パラメータ調整（環境変数）
- CMA_LLM_MAX_TOKENS (default: 1024)
- CMA_LLM_TEMPERATURE (default: 0.2)
- CMA_LLM_JSON_ENFORCE (default: true)
- CMA_LLM_REASONING_EFFORT (low|medium|high, default: medium)
- CMA_LLM_TIMEOUT_SEC (default: 30)

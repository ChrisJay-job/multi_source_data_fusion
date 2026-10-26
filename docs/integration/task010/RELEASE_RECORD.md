# TASK-010 attempt-001 鍙戝竷涓庝氦鎺ヨ褰?

鏃ユ湡锛?026-10-26锛圓sia/Shanghai锛? 
**鐘舵€侊細`MAIN_INTEGRATED_REMOTE_VERIFIED_HANDOFF_READY`**

鏈褰曚负鑱旇皟閮ㄧ讲鏉冨▉鍏ュ彛銆傚叕鍙?Linux / Broker / TLS / 鍓嶇 topic 鍙傛暟浠嶄负寰呭～鍐欙紱**鏈?*瀹ｇО鍏徃鐢熶骇宸蹭笂绾裤€?

---

## 1. Git 鎿嶄綔缁撴灉

| 椤?| 鍊?|
|---|---|
| 宸ヤ綔鏁村悎鏍?| `D:\zwyl\02_algo_project\multi_source_data_fusion_wt_task010_integ`锛堥殧绂?worktree锛屾湭鍔?TASK-004/005/006 dirty锛?|
| 涓氬姟鎻愪氦绾?| `task-008-mqtt-realtime-and-point-inspection` |
| 涓氬姟 commit | `73182f5d8846c209b5d2a0eb888863deefa5edf7`锛堝凡瀹?TASK-008/009 + TASK-010 鏂囨。/閮ㄧ讲锛?|
| 娴嬭瘯瀵归綈 commit | `665613e3e152620e1c0eb1853638d19fab9d7cbd`锛圱ASK-007 鍥炲綊閫傞厤 idle TTL / idempotency 棰勭畻锛?|
| **鏈€缁?local main** | `665613e3e152620e1c0eb1853638d19fab9d7cbd` |
| **鏈€缁?remote `origin/main`** | `665613e3e152620e1c0eb1853638d19fab9d7cbd`锛坄git ls-remote` 鐙珛鍥炶涓€鑷达級 |
| 杩滅▼ | `https://github.com/ChrisJay-job/multi_source_data_fusion.git`锛堟鍓嶆棤 heads锛涙湰娆?*鏂板缓**骞舵帹閫?`main`锛岄潪瀹ｇО鍘嗗彶宸插悓姝ワ級 |
| 鎺ㄩ€?| 鏅€?`git push -u origin main` / 鍚庣画 `git push origin main`锛?*鏈?* `--force` |
| 鍩虹嚎 tag | `task-007-multisensor-v1-map-r2-reviewed` 鈫?`badcaf8鈥 浠嶄繚鐣欙紱鏈疆**鏈?*鏂板缓鍐荤粨 tag |

淇濇姢锛氫富浠?`task-004-*` dirty銆乀ASK-005/006 worktree 鏈垏鎹?鏈竻鐞嗭紱鏈彁浜?`passwd_task008`銆佸鎴?CSV/SQL銆乣.env`銆佸鏌ュぇ ZIP銆?

---

## 2. 涓氬姟鎸囩汗锛堜笌 TASK-009 閿佷竴鑷达級

鏈€缁?main 鏍?13 鏂囦欢 SHA 涓?`SOURCE_LOCK.json` / 瑁佸喅 搂3 涓€鑷达紙鍚堝苟鍚庡鏍?`fp13=true`锛夛細

| 鏂囦欢 | SHA-256 |
|---|---|
| demo/workbench/app.js | `67c11ee3鈥?8733f` |
| demo/workbench/track3d.js | `1f933bf2鈥?45bc6` |
| demo/workbench/ux_query.js | `2876d466鈥?eb99c` |
| demo/workbench/ux_panel.js | `f2713a75鈥c8e632` |
| demo/workbench/ux_helpers.js | `7702bd07鈥?20eb8` |
| demo/workbench/canvas.js | `15e8268e鈥?65cb6` |
| demo/workbench/styles.css | `9db094de鈥?88e18` |
| demo/workbench/index.html | `26717ad5鈥5b483` |
| src/fusion_mvp/multisensor.py | `f4dfbc63鈥cfa66` |
| config/fusion.yaml | `e25f3560鈥?7df518` |
| src/fusion_mvp/api.py | `12ce8bd7鈥86f66` |
| src/fusion_mvp/workbench/mqtt_stream_job.py | `1390adf0鈥?71bf5` |
| src/fusion_mvp/integration/mqtt_bridge.py | `d5daeeb9鈥93a51` |

瀹屾暣鍝堝笇瑙佸悓鐩綍 `SOURCE_LOCK.json`銆?

---

## 3. 楠岃瘉缁撴灉锛堝悎骞跺悗涓€娆℃敹鏁涳級

| 椤?| 缁撴灉 |
|---|---|
| Python 3.11 鍏ㄩ噺 pytest锛圠inux 瀹瑰櫒锛?| **312 passed, 2 skipped**锛堝凡鐭ュ閮?XLS 绫?skip锛夛紱璇佹嵁 `reports/task010/evidence/pytest_full.log` |
| Compose `config --quiet` | 閫氳繃 |
| Docker Linux 闀滃儚鏋勫缓 | `fusion-integration:665613e`锛汭d `sha256:b8ee13d44f0c2fd2e5b83c688e7ad05d1887e7abd86da093a98e3e0069a3cc44`锛?*linux/amd64** |
| HTTP 鍐掔儫锛堢幆鍥?**18199**锛屾湭鍔ㄦ棦鏈?18099锛?| `/ready` 鍚?algorithmVersion=`mvp-0.1.0+task008-3d`銆乧onfig/multisensor SHA 涓庨攣涓€鑷达紱process/flush/replay 200锛涙捣鎷旀牱渚?datum=`MSL`锛涢潤鎬?`app.js` SHA 鍖归厤 |
| OpenAPI 蹇収 | `reports/task010/evidence/openapi.json` |
| 鍚堟垚 examples | `examples/integration/build_examples.py` 宸茬敓鎴愶紱浠呭悎鎴?SN |
| MQTT 鍒跺搧绾х煭娴?| **NOT_TESTED**锛堟湰鏈?1883 TCP 鍙揪锛屼絾鏈湪闅旂 tenant 涓婅窇閫傞厤鍣ㄦ敹鍙戯紝閬垮厤纰扮幇鏈夎仈璋?Broker 璐﹀彿锛夛紱涓氬姟鐭祴鍙户缁紩鐢?TASK-009 R2 UI 鐭祴璁板綍锛岀増鏈璇ュ寘 |
| 鍏徃 Linux 閮ㄧ讲 | **鏈墽琛?* |

---

## 4. 浜や粯鍒跺搧

| 鍒跺搧 | 璺緞锛堢浉瀵逛粨搴撴垨浜や粯鐩綍锛?| SHA-256 | 瀛楄妭 |
|---|---|---|---|
| Linux 婧愮爜鍖?| `reports/task010/artifacts/TASK-010-attempt-001-linux-source-665613e.tar.gz` | `1e29572cf95d4dcfb9d26da345499c0d49df7903fd8716c1f733d974ca1b43b9` | 1091264 |
| 楠岃瘉闀滃儚锛坓zip锛?| `reports/task010/artifacts/fusion-integration-665613e.tar.gz` | `5d4e812396df973914396f6a76be3aa4ead8b2d648302f01d4e9bf4b625fec7a` | 130314919 |
| 瀹℃煡浜ゆ帴 ZIP | `review_zip/TASK-010-attempt-001-integration-release-review-bundle.zip` | 锛堟墦鍖呭悗鍐欏叆鍖呭 `.sha256.txt` / `.bytes.txt`锛?| 鈥?|

闀滃儚鏍囩锛歚fusion-integration:665613e` / `fusion-integration:local`銆傛湰鍦?RepoDigests 瀛楁涓洪暅鍍忚嚜寮曠敤 digest锛?*闈?* registry 鎷夊彇 digest锛夛紱绂荤嚎鏈虹敤 `docker load -i 鈥ar.gz`銆?

婧愮爜鍖呭惈锛歚COMMIT.txt`=`665613e3e152620e1c0eb1853638d19fab9d7cbd`锛岃繍琛屽繀闇€婧愮爜/config/demo/scripts銆乺equirements銆侀儴缃蹭笌浜ゆ帴鏂囨。銆佸悎鎴?examples銆佺浉鍏虫祴璇曪紱**涓嶅惈**鐪熷疄 `.env`銆乸asswd銆佸鎴锋暟鎹€乨ata 搴撱€乿env銆佸巻鍙插鏌ュぇ鍖呫€侀暅鍍忔湰浣撱€?

---

## 5. 鏉冨▉鍏ュ彛锛堢粰鍚屼簨锛?

1. **閮ㄧ讲锛?* `docs/integration/task010/01_LINUX_DEPLOY.md` + `deploy/integration/`  
2. **鍚庣瀛楁/API锛?* `docs/integration/task010/02_API_FIELD_DICTIONARY.md`  
3. **涓夋柟娴佺▼锛?* `docs/integration/task010/03_REALTIME_INTEGRATION.md`  
4. **鍓嶇缁樺浘宸ヤ綔鍙帮細** 鏈嶅姟鏍?`/` 鎴?`/demo/workbench`锛堥潤鎬佷笌 HTTP API 鍚岃繘绋嬶紝workers=1锛? 
5. **鍙戝竷鎸囩汗锛?* 鏈枃浠?+ `SOURCE_LOCK.json`

### 5 鍒嗛挓鍐掔儫椤哄簭锛堢洰鏍?Linux锛?

1. `docker load` 闀滃儚鎴?`compose build`锛涘～鍐?`.env.integration`锛堟潈闄?600锛夈€? 
2. `compose config --quiet` 鈫?`up -d fusion-core`锛堥粯璁や粎 127.0.0.1锛夈€? 
3. `GET /ready` 鏍稿 config/multisensor SHA銆? 
4. 鐢?`examples/integration/build_examples.py` 鐢熸垚鍚堟垚璇锋眰 鈫?`POST /v1/fusion/process` 鈫?flush 鈫?replay銆? 
5. 鍙€夛細`--profile mqtt` 鍚€傞厤鍣紙闇€宸叉壒鍑?Broker锛涘綋鍓嶉€傞厤鍣?*鏃犲師鐢?TLS 鍙橀噺**锛夈€?

### 椋炶鍚庤ˉ榻?

**鏃?*涓撶敤闀挎柇鐐硅ˉ榻愭帴鍙ｃ€俙run.end` 浠呮帓绌猴紱`replay` 涓轰复鏃舵帓搴忛噸鏀俱€傜幇闃舵锛氬垎娈靛綊妗ｃ€佹寜鍙俊 SN 鍒嗙粍灞曠ず骞舵爣鏄庣己鍙ｏ紱涓嶈鐢ㄥ疄绾挎帺鐩栨棤瑙傛祴鏃舵銆傝瑙?`05_POSTFLIGHT_AND_GAPS.md`銆?

---

## 6. 寰呯幆澧冪‘璁わ紙鍗犱綅锛岄潪宸查儴缃诧級

- 鍏徃 Linux 涓绘満 / 鏋舵瀯 / 闅旂绔彛  
- Broker host/port/璐﹀彿/ACL/TLS 缁堟鏂瑰紡  
- tenant/site銆佸墠绔笟鍔?topic銆佺綉鍏抽壌鏉? 
- 鎸佷箙鏁版嵁鐩綍涓庡浠借矗浠讳汉  

---

## 7. 鏈仛鍔ㄤ綔

- 鏈叕鍙哥敓浜ч儴缃层€佹湭寮烘帹銆佹湭鏀瑰凡瀹＄畻娉曟寚绾广€佹湭鏂板鏂偣琛ラ綈绠楁硶/鎺ュ彛  
- 鏈紑濮嬪叾浠栫爺鍙戦樁娈碉紱鏈柊寤哄喕缁?tag  


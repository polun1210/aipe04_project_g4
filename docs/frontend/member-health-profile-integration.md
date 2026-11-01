# Google 登入與健康資料串接（前端現況）

只有 Google 登入：不提供註冊頁與密碼；名字與 email 由 Google 提供。Google 沒有生日與性別，所以第一次登入後要在 `/health-profile` 填 4 項（出生年、出生月、性別、慢性病），全部必填。填過的人登入後直接開始評估，之後在 `/settings` 修改。

```
/login（Google 按鈕）
   │ 登入成功
   ├─ profile_completed = false ──→ /health-profile ──儲存成功──→ redirect 或 /medicine-upload
   └─ profile_completed = true  ──→ redirect 或 /medicine-upload
```

## API 約定

全部走 `apiRequest`（`src/api/client.ts`），路徑為 `/api/...`，經 Vite 轉發，同源，cookie 自動帶上。

| 方法與網址 | 送出 | 成功 | 失敗 |
|---|---|---|---|
| `POST /api/auth/google` | `{"credential": string}` | 200 `Me` | 401 `unauthorized`；404（後端是測試模式） |
| `GET /api/me` | — | 200 `Me` | 401（沒登入） |
| `POST /api/logout` | — | 204 | — |
| `GET /api/me/profile` | — | 200 `AccountProfile` | 404（還沒填）；401 |
| `PUT /api/me/profile` | `AccountProfile` | 200 `AccountProfile` | 422；401 |
| `POST /api/assessments` | 不變 | 不變 | 新增 409 `profile_incomplete` |

`Me = { user_id, email, name, profile_completed }`；`AccountProfile` 見 `src/models/healthProfile.ts`。後端預設 `AUTH=test`：`GET /api/me` 回測試帳號且 `profile_completed: true`，本機不設 Google 也能走完評估。

## 前端結構

- `src/api/auth.ts`：`getMe`（401 回 `null`）、`loginWithGoogle`、`logout`、`getProfile`（404 回 `null`）、`saveProfile`。
- `src/stores/session.ts`（Pinia）：`me`、`loaded`、`load()`、`login()`、`logout()`、`markProfileCompleted()`。
- `src/router/authGuard.ts`：純函式 `resolveAuthRedirect(to, me)` 與 `safeRedirect()`；`router.beforeEach` 先 `session.load()` 再呼叫。
  - 需登入：會員中心、設定、健康資料、藥品／保健食品流程、報告。沒登入 → `/login?redirect=…`。
  - 需填過健康資料：藥品／保健食品上傳與核對。沒填 → `/health-profile?redirect=…`。
  - 已登入進 `/login` → `/medicine-upload`。
  - `redirect` 只接受 `/` 開頭、非 `//` 開頭的站內路徑。
- `src/services/healthProfileApi.ts`：`HealthProfileGateway` 的真實作，由 `main.ts` provide。首次填寫與日後修改都用 `saveProfile`（`saveInitialConditions` 已移除）。
- `SupplementReviewView.vue`：送出評估收到 409 `profile_incomplete` → 導到 `/health-profile`（帶 redirect），資料留在 store。
- `/register` 轉址到 `/login`；`RegisterView.vue` 與設定頁的密碼介面已移除。

## Client ID

讀 `VITE_GOOGLE_CLIENT_ID`（範例見 `frontend/.env.example`，真值放 `frontend/.env.local`，不進 git）；需與後端 `.env` 的 `GOOGLE_CLIENT_ID` 同一個值。沒設定時登入頁顯示「Google 登入尚未設定」。

## 測試

`npm run test:auth-guard`（路由判斷）、`npm run test:health-profile`、`npm run test:health-profile-browser`（需要 Chrome）。

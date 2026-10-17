// API 串接練習，尚未接入正式頁面，待團隊整合
export interface ApiErrorBody {
  code: string
  message: string
  details?: string[]
}

export interface ApiErrorResponse {
  error: ApiErrorBody
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorResponse,
  ) {
    super(body.error.message)
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  // 判斷這次是否要上傳圖片或檔案
  const isFormData = options.body instanceof FormData

  // 整理呼叫端傳進來的 headers
  const headers = new Headers(options.headers)

  // FormData 的 Content-Type 交給瀏覽器自動設定
  if (isFormData) {
    headers.delete('Content-Type')
  } else if (options.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...options,
    headers,
  })

  // 請求失敗：試著讀取後端的錯誤訊息
  if (!response.ok) {
    const body = await response.json().catch(() => null)

    throw new ApiError(
      response.status,
      body ?? {
        error: {
          code: 'network_error',
          message: '無法完成請求，請確認後端已啟動或稍後再試',
        },
      },
    )
  }

  // 請求成功：將 JSON 資料交給呼叫它的程式
  return (await response.json()) as T
}
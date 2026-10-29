import { inject, type InjectionKey } from 'vue'

// Only the isolated demo application provides this context. Query parameters or
// normal Pinia state never enable demo exceptions in the regular application.
export interface ReviewDemoContext {
  finish(): Promise<unknown>
}
export const reviewDemoKey: InjectionKey<ReviewDemoContext> = Symbol('reviewDemo')
export function useReviewDemo() {
  return inject(reviewDemoKey, null)
}

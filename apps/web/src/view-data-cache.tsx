import { createContext, type Dispatch, type ReactNode, type SetStateAction, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from "react";

const ViewDataCacheContext = createContext<Map<string, unknown> | null>(null);
const viewDataCacheLimit = 128;

function touchCacheValue<T>(cache: Map<string, unknown>, key: string, value: T) {
  cache.delete(key);
  cache.set(key, value);
  while (cache.size > viewDataCacheLimit) {
    const oldestKey = cache.keys().next().value;
    if (typeof oldestKey !== "string") break;
    cache.delete(oldestKey);
  }
}

export function ViewDataCacheProvider({ scope, children }: { scope: string; children: ReactNode }) {
  const cacheRef = useRef<{ scope: string; values: Map<string, unknown> }>({ scope, values: new Map() });
  if (cacheRef.current.scope !== scope) cacheRef.current = { scope, values: new Map() };
  return <ViewDataCacheContext.Provider value={cacheRef.current.values}>{children}</ViewDataCacheContext.Provider>;
}

export function useCachedViewState<T>(key: string, initialValue: T): [T, Dispatch<SetStateAction<T>>, boolean] {
  const cache = useContext(ViewDataCacheContext);
  if (!cache) throw new Error("useCachedViewState must be used inside ViewDataCacheProvider");
  const initialValueRef = useRef(initialValue);

  const read = useCallback(() => {
    const hasValue = cache.has(key);
    const value = hasValue ? cache.get(key) as T : initialValueRef.current;
    if (hasValue) touchCacheValue(cache, key, value);
    return { value, hasValue };
  }, [cache, key]);
  const [entry, setEntry] = useState(read);

  useLayoutEffect(() => {
    setEntry(read());
  }, [read]);

  const setValue = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    setEntry((current) => {
      const value = typeof next === "function"
        ? (next as (previous: T) => T)(current.value)
        : next;
      touchCacheValue(cache, key, value);
      return { value, hasValue: true };
    });
  }, [cache, key]);

  return useMemo(() => [entry.value, setValue, entry.hasValue], [entry.hasValue, entry.value, setValue]);
}

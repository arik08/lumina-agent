import { ArrowRight, AtSign, KeyRound, LoaderCircle, ShieldCheck, Sparkles } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { ApiError, login } from "../api";
import type { AuthSession } from "../api-types";
import "../login.css";

export interface LoginScreenProps {
  onAuthenticated: (session: AuthSession) => void;
  initialDomain?: string;
}

export function LoginScreen({ onAuthenticated, initialDomain = "posco.com" }: LoginScreenProps) {
  const [loginName, setLoginName] = useState("");
  const [loginDomain, setLoginDomain] = useState(initialDomain);
  const [password, setPassword] = useState("");
  const [domainEditing, setDomainEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    const normalizedName = loginName.trim();
    const normalizedDomain = loginDomain.trim().replace(/^@+/, "");
    if (!normalizedName || !normalizedDomain || !password) {
      setError("아이디, 주소와 비밀번호를 모두 입력해 주세요.");
      if (!password) passwordRef.current?.focus();
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const session = await login({
        loginName: normalizedName,
        loginDomain: normalizedDomain,
        password,
      });
      onAuthenticated(session);
    } catch (caught) {
      setPassword("");
      setError(
        caught instanceof ApiError && caught.status >= 500
          ? "로그인 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
          : "아이디, 주소 또는 비밀번호를 확인해 주세요.",
      );
      window.requestAnimationFrame(() => passwordRef.current?.focus());
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-screen">
      <section className="login-layout" aria-labelledby="login-heading">
        <div className="login-story">
          <a className="login-wordmark" href="/" aria-label="Lumina 홈">
            <Sparkles size={22} strokeWidth={1.7} aria-hidden="true" />
            <span>Lumina</span>
          </a>

          <div className="login-story-copy">
            <p className="login-eyebrow">UNDERSTAND. CONNECT. NAVIGATE. ACT.</p>
            <h1 id="login-heading">작업의 흐름을<br />놓치지 않는 Agent</h1>
            <p>대화, 실행 과정과 산출물을 하나의 Project 안에서 안전하게 이어갑니다.</p>
          </div>

          <div className="login-trust-note">
            <ShieldCheck size={18} aria-hidden="true" />
            <span>회사 계정과 서버 세션으로 보호됩니다.</span>
          </div>
        </div>

        <div className="login-form-area">
          <div className="login-form-heading">
            <span className="login-form-icon"><KeyRound size={19} aria-hidden="true" /></span>
            <div>
              <h2>다시 만나서 반갑습니다</h2>
              <p>회사 계정으로 Lumina에 로그인해 주세요.</p>
            </div>
          </div>

          <form className="login-form" noValidate onSubmit={submit}>
            {import.meta.env.DEV && (
              <button
                className="login-dev-account"
                type="button"
                disabled={submitting}
                onClick={() => {
                  setLoginName("admin");
                  setLoginDomain("posco.com");
                  passwordRef.current?.focus();
                }}
              >
                개발 계정 admin@posco.com 채우기
              </button>
            )}
            <label className="login-field" htmlFor="lumina-login-name">
              <span>아이디</span>
              <input
                id="lumina-login-name"
                autoComplete="username"
                autoFocus
                disabled={submitting}
                inputMode="text"
                placeholder="admin"
                value={loginName}
                onChange={(event) => setLoginName(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Tab" && !event.shiftKey) {
                    event.preventDefault();
                    passwordRef.current?.focus();
                  }
                }}
              />
            </label>

            <div className="login-domain-control">
              <span className="login-domain-label">주소</span>
              <div className="login-domain-value">
                <AtSign size={15} aria-hidden="true" />
                {domainEditing ? (
                  <input
                    aria-label="로그인 주소"
                    autoFocus
                    disabled={submitting}
                    value={loginDomain}
                    onBlur={() => setDomainEditing(false)}
                    onChange={(event) => setLoginDomain(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === "Escape") {
                        event.preventDefault();
                        setDomainEditing(false);
                        passwordRef.current?.focus();
                      }
                    }}
                  />
                ) : (
                  <strong>{loginDomain}</strong>
                )}
              </div>
              <button
                type="button"
                disabled={submitting}
                onClick={() => {
                  if (domainEditing) passwordRef.current?.focus();
                  setDomainEditing(!domainEditing);
                }}
              >
                {domainEditing ? "완료" : "주소 변경"}
              </button>
            </div>

            <label className="login-field" htmlFor="lumina-password">
              <span>비밀번호</span>
              <input
                id="lumina-password"
                ref={passwordRef}
                autoComplete="current-password"
                disabled={submitting}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.currentTarget.value)}
              />
            </label>

            <div className="login-error" aria-live="polite" role={error ? "alert" : undefined}>
              {error}
            </div>

            <button className="login-submit" type="submit" disabled={submitting}>
              {submitting ? (
                <><LoaderCircle className="login-spinner" size={17} aria-hidden="true" /> 로그인 중</>
              ) : (
                <>로그인 <ArrowRight size={17} aria-hidden="true" /></>
              )}
            </button>
          </form>

          <p className="login-session-note">인증된 세션은 오늘 자정까지 유지됩니다.</p>
        </div>
      </section>
    </main>
  );
}

export default LoginScreen;

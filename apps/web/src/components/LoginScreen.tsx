import { ArrowRight, AtSign, KeyRound, LoaderCircle, ShieldCheck, Sparkles, UserPlus } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { ApiError, login, registerAccount } from "../api";
import type { AuthSession, UserRole } from "../api-types";
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
  const [registering, setRegistering] = useState(false);
  const [registrationEmail, setRegistrationEmail] = useState("");
  const [registrationName, setRegistrationName] = useState("");
  const [registrationAffiliation, setRegistrationAffiliation] = useState("");
  const [registrationRole, setRegistrationRole] = useState<UserRole>("user");
  const [registrationPassword, setRegistrationPassword] = useState("");
  const [registrationPasswordConfirm, setRegistrationPasswordConfirm] = useState("");
  const [registrationMessage, setRegistrationMessage] = useState<string | null>(null);
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

  const submitRegistration = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    if (!registrationEmail.trim() || !registrationName.trim() || !registrationAffiliation.trim()) {
      setError("이메일, 이름과 소속을 모두 입력해 주세요.");
      return;
    }
    if (registrationPassword.length < 8) {
      setError("비밀번호는 8자 이상 입력해 주세요.");
      return;
    }
    if (registrationPassword !== registrationPasswordConfirm) {
      setError("비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await registerAccount({
        email: registrationEmail.trim(),
        displayName: registrationName.trim(),
        affiliation: registrationAffiliation.trim(),
        role: registrationRole,
        password: registrationPassword,
      });
      setRegistrationMessage(result.message);
      setRegistrationPassword("");
      setRegistrationPasswordConfirm("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "가입 신청을 접수하지 못했습니다.");
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

          {!registering ? <form className="login-form" noValidate onSubmit={submit}>
            {import.meta.env.DEV && (
              <button
                className="login-dev-account"
                type="button"
                aria-label="개발 계정 admin@posco.com 채우기"
                disabled={submitting}
                onClick={() => {
                  setLoginName("admin");
                  setLoginDomain("posco.com");
                  passwordRef.current?.focus();
                }}
              >
                <UserPlus size={16} strokeWidth={1.8} aria-hidden="true" />
                <span className="login-dev-account-tooltip" role="tooltip">
                  개발 계정 admin@posco.com 채우기
                </span>
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
                placeholder="POSCO_계정명"
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
            <button className="login-register-open" type="button" onClick={() => { setRegistering(true); setError(null); }}>
              회원가입
            </button>
          </form> : (
            <form className="login-form login-registration-form" noValidate onSubmit={submitRegistration}>
              <div className="login-registration-heading">
                <strong>회원가입 신청</strong>
                <span>관리자 승인 후 로그인할 수 있습니다.</span>
              </div>
              <label className="login-field"><span>이메일</span><input aria-label="가입 이메일" type="email" autoComplete="email" placeholder="account@posco.com" value={registrationEmail} onChange={(event) => setRegistrationEmail(event.currentTarget.value)} /></label>
              <label className="login-field"><span>이름</span><input aria-label="이름" autoComplete="name" value={registrationName} onChange={(event) => setRegistrationName(event.currentTarget.value)} /></label>
              <label className="login-field"><span>소속</span><input aria-label="소속" value={registrationAffiliation} onChange={(event) => setRegistrationAffiliation(event.currentTarget.value)} /></label>
              <label className="login-field"><span>권한</span><select aria-label="신청 역할" value={registrationRole} onChange={(event) => setRegistrationRole(event.currentTarget.value as UserRole)}><option value="user">사용자</option><option value="admin">관리자</option></select></label>
              <div className="login-registration-passwords">
                <label className="login-field"><span>비밀번호</span><input aria-label="가입 비밀번호" type="password" autoComplete="new-password" value={registrationPassword} onChange={(event) => setRegistrationPassword(event.currentTarget.value)} /></label>
                <label className="login-field"><span>비밀번호 확인</span><input aria-label="비밀번호 확인" type="password" autoComplete="new-password" value={registrationPasswordConfirm} onChange={(event) => setRegistrationPasswordConfirm(event.currentTarget.value)} /></label>
              </div>
              <div className="login-error" aria-live="polite" role={error ? "alert" : undefined}>{error}</div>
              {registrationMessage && <p className="login-registration-success" role="status">{registrationMessage}</p>}
              <button className="login-submit" type="submit" disabled={submitting || Boolean(registrationMessage)}>{submitting ? "신청 중" : "가입 신청"}</button>
              <button className="login-register-open" type="button" onClick={() => { setRegistering(false); setError(null); setRegistrationMessage(null); }}>로그인으로 돌아가기</button>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}

export default LoginScreen;

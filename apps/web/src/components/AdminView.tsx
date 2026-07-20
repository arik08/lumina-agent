import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  Download,
  FileText,
  KeyRound,
  List,
  LoaderCircle,
  Menu,
  MessageSquare,
  PlayCircle,
  Plus,
  RefreshCcw,
  Save,
  Search,
  ShieldCheck,
  Users,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  AdminAuditEvent,
  AdminConversationDetail,
  AdminConversationSummary,
  AdminUser,
  AdminUsageStatistics,
  UserRole,
  UserStatus,
} from "../api-types";
import { AdminTrafficChart } from "./AdminTrafficChart";
import { OrganizationInstructionsPanel } from "./OrganizationInstructionsPanel";
import { SelectMenu } from "./SelectMenu";

type AdminTab = "users" | "usage" | "conversations" | "audit" | "policy";
type UsageMetric = "activeUsers" | "loginCount" | "runCount";
type AdminHistoryViewMode = "recent" | "user";
type AdminListLimit = 50 | 120 | 250 | 500;

interface AdminViewProps {
  onOpenNavigation: () => void;
  onToast: (message: string) => void;
  onUserUpdated: () => void;
}

const userStatuses: Array<{ value: UserStatus; label: string }> = [
  { value: "active", label: "활성" },
  { value: "invited", label: "초대됨" },
  { value: "locked", label: "잠김" },
  { value: "disabled", label: "비활성" },
];

function userRoleLabel(role: UserRole) {
  return role === "admin" ? "관리자" : "사용자";
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

const usageMetricLabels: Record<UsageMetric, string> = {
  activeUsers: "활동 사용자",
  loginCount: "접속 횟수",
  runCount: "Run",
};

const adminListLimits: AdminListLimit[] = [50, 120, 250, 500];
const adminListLimitOptions = adminListLimits.map((limit) => ({ value: String(limit), label: `${limit}건` }));
const userRoleOptions = [{ value: "user", label: "사용자" }, { value: "admin", label: "관리자" }];
const usagePeriodOptions = [{ value: "30", label: "최근 30일" }, { value: "90", label: "최근 90일" }, { value: "0", label: "전체" }];

function UsageTrendChart({ statistics, metric }: { statistics: AdminUsageStatistics; metric: UsageMetric }) {
  const values = statistics.trend.map((item) => item[metric]);
  const max = Math.max(1, ...values);
  const width = 960;
  const height = 210;
  const inset = { top: 14, right: 12, bottom: 28, left: 30 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const points = statistics.trend.map((item, index) => ({
    ...item,
    x: inset.left + (statistics.trend.length === 1 ? 0 : index / (statistics.trend.length - 1)) * plotWidth,
    y: inset.top + plotHeight - (item[metric] / max) * plotHeight,
  }));
  const line = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = points.length ? `${line} L${points.at(-1)?.x},${inset.top + plotHeight} L${points[0].x},${inset.top + plotHeight} Z` : "";
  const labelEvery = Math.max(1, Math.ceil(statistics.trend.length / 6));
  return (
    <div className="admin-usage-chart-wrap">
      <svg className="admin-usage-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${usageMetricLabels[metric]} ${statistics.periodDays}일 추이`}>
        {[0, 0.5, 1].map((ratio) => <g key={ratio}><line x1={inset.left} x2={width - inset.right} y1={inset.top + plotHeight * ratio} y2={inset.top + plotHeight * ratio} /><text x={inset.left - 7} y={inset.top + plotHeight * ratio + 4}>{Math.round(max * (1 - ratio))}</text></g>)}
        <path className="admin-usage-area" d={area} />
        <path className="admin-usage-line" d={line} />
        {points.map((point, index) => <g className="admin-usage-point" key={point.date}><circle cx={point.x} cy={point.y} r="3"><title>{point.date} · {point[metric]}{metric === "activeUsers" ? "명" : "회"}</title></circle>{(index % labelEvery === 0 || index === points.length - 1) && <text className="admin-usage-date" x={point.x} y={height - 7}>{point.date.slice(5)}</text>}</g>)}
      </svg>
    </div>
  );
}

export function AdminView({ onOpenNavigation, onToast, onUserUpdated }: AdminViewProps) {
  const [tab, setTab] = useState<AdminTab>("users");
  const [query, setQuery] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usageStatistics, setUsageStatistics] = useState<AdminUsageStatistics | null>(null);
  const [usagePeriod, setUsagePeriod] = useState<0 | 30 | 90>(30);
  const [usageMetric, setUsageMetric] = useState<UsageMetric>("activeUsers");
  const [userTotal, setUserTotal] = useState(0);
  const [conversations, setConversations] = useState<AdminConversationSummary[]>([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationViewMode, setConversationViewMode] = useState<AdminHistoryViewMode>("recent");
  const [conversationLimit, setConversationLimit] = useState<AdminListLimit>(120);
  const [collapsedConversationUsers, setCollapsedConversationUsers] = useState<Set<string>>(new Set());
  const [feedbackOnly, setFeedbackOnly] = useState(false);
  const [exportingConversations, setExportingConversations] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AdminAuditEvent[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditLimit, setAuditLimit] = useState<AdminListLimit>(120);
  const [auditViewMode, setAuditViewMode] = useState<AdminHistoryViewMode>("recent");
  const [collapsedAuditUsers, setCollapsedAuditUsers] = useState<Set<string>>(new Set());
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  const [userDisplayName, setUserDisplayName] = useState("");
  const [userAffiliation, setUserAffiliation] = useState("");
  const [userRole, setUserRole] = useState<UserRole>("user");
  const [userStatus, setUserStatus] = useState<UserStatus>("active");
  const [userChangeArmed, setUserChangeArmed] = useState(false);
  const [resetPassword, setResetPassword] = useState("");
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [passwordResetArmed, setPasswordResetArmed] = useState(false);
  const [selectedConversation, setSelectedConversation] = useState<AdminConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createLoginName, setCreateLoginName] = useState("");
  const [createLoginDomain, setCreateLoginDomain] = useState("posco.com");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createAffiliation, setCreateAffiliation] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] = useState<UserRole>("user");
  const [saving, setSaving] = useState(false);
  const auditEventsByUser = useMemo(() => {
    const groups = new Map<string, AdminAuditEvent[]>();
    auditEvents.forEach((event) => {
      const userId = event.actorLoginId ?? event.actorUserId ?? "시스템";
      groups.set(userId, [...(groups.get(userId) ?? []), event]);
    });
    return [...groups.entries()];
  }, [auditEvents]);

  const conversationsByUser = useMemo(() => {
    const groups = new Map<string, AdminConversationSummary[]>();
    conversations.forEach((conversation) => {
      const userId = conversation.owner.loginId;
      groups.set(userId, [...(groups.get(userId) ?? []), conversation]);
    });
    return [...groups.entries()];
  }, [conversations]);

  useEffect(() => {
    if (tab === "policy" || tab === "usage") {
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      const request = tab === "users"
        ? api.admin.listUsers({ query, limit: 100 }, controller.signal).then((page) => {
            setUsers(page.items);
            setUserTotal(page.total);
          })
        : tab === "conversations"
          ? api.admin.listConversations({ query, feedbackOnly, limit: conversationLimit }, controller.signal).then((page) => {
              setConversations(page.items);
              setConversationTotal(page.total);
            })
          : api.admin.listAuditEvents({ action: query, limit: auditLimit }, controller.signal).then((page) => {
              setAuditEvents(page.items);
              setAuditTotal(page.total);
            });
      request.catch((requestError) => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      }).finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [auditLimit, conversationLimit, feedbackOnly, query, refreshKey, tab]);

  useEffect(() => {
    if (tab !== "usage" && tab !== "audit") return;
    const controller = new AbortController();
    if (tab === "usage") setLoading(true);
    setError(null);
    void api.admin.getUsageStatistics(usagePeriod, controller.signal)
      .then(setUsageStatistics)
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (!controller.signal.aborted && tab === "usage") setLoading(false);
      });
    return () => controller.abort();
  }, [refreshKey, tab, usagePeriod]);

  const chooseUser = (user: AdminUser) => {
    const next = selectedUser?.id === user.id ? null : user;
    setSelectedUser(next);
    setUserDisplayName(next?.displayName ?? "");
    setUserAffiliation(next?.affiliation ?? "");
    setUserRole(next?.role ?? "user");
    setUserStatus(next?.status ?? "active");
    setUserChangeArmed(false);
    setResetPassword("");
    setMustChangePassword(false);
    setPasswordResetArmed(false);
  };

  const createUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!createLoginName.trim() || !createPassword) return;
    setSaving(true);
    try {
      await api.admin.createUser({
        loginName: createLoginName.trim(),
        loginDomain: createLoginDomain.trim() || "posco.com",
        password: createPassword,
        displayName: createDisplayName.trim() || null,
        affiliation: createAffiliation.trim() || null,
        role: createRole,
        status: "active",
        mustChangePassword: false,
      });
      setCreateLoginName("");
      setCreateDisplayName("");
      setCreateAffiliation("");
      setCreatePassword("");
      setCreateRole("user");
      setCreateOpen(false);
      setRefreshKey((value) => value + 1);
      onToast("사용자를 생성했습니다. 입력한 비밀번호는 다시 표시되지 않습니다.");
    } catch (requestError) {
      onToast(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const saveUser = async () => {
    if (!selectedUser) return;
    const destructive = userRole !== selectedUser.role || userStatus !== selectedUser.status;
    if (destructive && !userChangeArmed) {
      setUserChangeArmed(true);
      return;
    }
    setSelectedUser(null);
    setSaving(true);
    try {
      const updated = await api.admin.updateUser(selectedUser.id, {
        displayName: userDisplayName.trim() || null,
        affiliation: userAffiliation.trim() || null,
        role: userRole,
        status: userStatus,
      });
      setUsers((items) => items.map((item) => item.id === updated.id ? updated : item));
      setUserChangeArmed(false);
      onUserUpdated();
    } catch (requestError) {
      onToast(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const approveUser = async (user: AdminUser) => {
    setSaving(true);
    try {
      const updated = await api.admin.updateUser(user.id, { status: "active" });
      setUsers((items) => items.map((item) => item.id === updated.id ? updated : item));
      onUserUpdated();
    } catch (requestError) {
      onToast(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const resetUserPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedUser || !resetPassword) return;
    if (!passwordResetArmed) {
      setPasswordResetArmed(true);
      return;
    }
    setSaving(true);
    try {
      const result = await api.admin.resetPassword(selectedUser.id, resetPassword, mustChangePassword);
      setResetPassword("");
      setMustChangePassword(false);
      setPasswordResetArmed(false);
      setSelectedUser(result.user);
      setUsers((items) => items.map((item) => item.id === result.user.id ? result.user : item));
      onToast(`비밀번호를 reset했습니다. 종료된 세션 ${result.revokedSessionCount}개 · 비밀번호는 다시 표시되지 않습니다.`);
    } catch (requestError) {
      onToast(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const openConversation = async (conversationId: string) => {
    setDetailLoading(true);
    try {
      setSelectedConversation(await api.admin.getConversation(conversationId));
    } catch (requestError) {
      onToast(errorMessage(requestError));
    } finally {
      setDetailLoading(false);
    }
  };

  const exportConversations = async () => {
    setExportingConversations(true);
    try {
      const download = await api.admin.exportConversations({
        query,
        feedbackOnly,
        limit: conversationLimit,
      });
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      onToast(errorMessage(requestError));
    } finally {
      setExportingConversations(false);
    }
  };

  const renderConversationRow = (conversation: AdminConversationSummary) => (
    <button className="admin-conversation-row" type="button" key={conversation.id} onClick={() => void openConversation(conversation.id)}>
      <span><strong>{conversation.title}</strong><small>{conversation.owner.loginId}</small><small>{formatDate(conversation.lastActivityAt)}</small></span>
      <span className="admin-conversation-meta"><i aria-hidden="true" /><span>{conversation.feedbackCount > 0 && <b className="admin-feedback-count">의견 {conversation.feedbackCount}</b>}</span><span>{conversation.runCount} Run · {conversation.artifactCount} 문서</span></span>
    </button>
  );

  const placeholder = tab === "users" || tab === "usage" ? "ID 또는 표시 이름 검색" : tab === "conversations" ? "대화 제목 검색" : "정확한 audit action 검색";
  const filteredUsageUsers = usageStatistics?.users.filter((user) => {
    const term = query.trim().toLocaleLowerCase();
    return !term || [user.loginId, user.displayName, user.affiliation].some((value) => value?.toLocaleLowerCase().includes(term));
  }) ?? [];

  return (
    <main className="feature-view admin-view" aria-label="시스템 관리 화면">
      <header className="workspace-view-header">
        <button className="mobile-menu-button" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={19} /></button>
        <div><h1>시스템 관리</h1><p>민감한 조회와 변경은 모니터링 로그에 기록됩니다.</p></div>
      </header>
      <div className="admin-toolbar">
        <div className="admin-tabs" role="tablist" aria-label="시스템 관리 항목">
          <button type="button" role="tab" aria-selected={tab === "users"} onClick={() => setTab("users")}><Users size={15} /> 사용자</button>
          <button type="button" role="tab" aria-selected={tab === "usage"} onClick={() => setTab("usage")}><BarChart3 size={15} /> 사용통계</button>
          <button type="button" role="tab" aria-selected={tab === "conversations"} onClick={() => setTab("conversations")}><MessageSquare size={15} /> 대화</button>
          <button type="button" role="tab" aria-selected={tab === "audit"} onClick={() => setTab("audit")}><ShieldCheck size={15} /> 모니터링</button>
          <button type="button" role="tab" aria-selected={tab === "policy"} onClick={() => setTab("policy")}><FileText size={15} /> 기본 지침</button>
        </div>
        {tab !== "policy" && <label className="admin-search"><Search size={15} /><input value={query} placeholder={placeholder} onChange={(event) => setQuery(event.currentTarget.value)} /></label>}
        {tab !== "policy" && <button className="tooltip-control" type="button" aria-label="새로 고침" data-tooltip="새로 고침" onClick={() => setRefreshKey((value) => value + 1)}>{loading ? <LoaderCircle className="is-running" size={16} /> : <RefreshCcw size={16} />}</button>}
        {tab === "conversations" && <label className="admin-feedback-filter"><input type="checkbox" checked={feedbackOnly} onChange={(event) => setFeedbackOnly(event.currentTarget.checked)} /> 의견 있는 대화만</label>}
        {tab === "users" && <button className="primary-compact lumina-primary-action" type="button" onClick={() => setCreateOpen((open) => !open)}><Plus size={15} /> 사용자</button>}
      </div>
      {error && <p className="workspace-error" role="alert">{error}</p>}

      {tab === "users" && (
        <section className="admin-section" aria-label="사용자 관리">
          {createOpen && (
            <form className="admin-inline-form admin-create-user" onSubmit={(event) => void createUser(event)}>
              <input aria-label="사용자 ID" placeholder="사용자 ID" value={createLoginName} onChange={(event) => setCreateLoginName(event.currentTarget.value)} required />
              <input aria-label="로그인 주소" placeholder="posco.com" value={createLoginDomain} onChange={(event) => setCreateLoginDomain(event.currentTarget.value)} required />
              <input aria-label="표시 이름" placeholder="표시 이름 (선택)" value={createDisplayName} onChange={(event) => setCreateDisplayName(event.currentTarget.value)} />
              <input aria-label="소속" placeholder="소속 (선택)" value={createAffiliation} onChange={(event) => setCreateAffiliation(event.currentTarget.value)} />
              <input aria-label="초기 비밀번호" type="password" autoComplete="new-password" placeholder="초기 비밀번호" value={createPassword} onChange={(event) => setCreatePassword(event.currentTarget.value)} required />
              <SelectMenu className="admin-form-select" size="small" value={createRole} options={userRoleOptions} ariaLabel="새 사용자 역할" onChange={(value) => setCreateRole(value as UserRole)} />
              <button type="submit" disabled={saving}>{saving ? <LoaderCircle className="is-running" size={14} /> : <Plus size={14} />} 생성</button>
            </form>
          )}
          <div className="admin-count">사용자 {userTotal}명</div>
          <div className="admin-list">
            {users.map((user) => (
              <article className={`admin-row ${selectedUser?.id === user.id ? "is-open" : ""}`} key={user.id}>
                {selectedUser?.id === user.id ? (
                  <form className="admin-user-inline-edit" onSubmit={(event) => { event.preventDefault(); void saveUser(); }} onKeyDown={(event) => { if (event.key !== "Enter") return; event.preventDefault(); void saveUser(); }}>
                    <strong data-tooltip={user.loginId}>{user.loginId}</strong>
                    <input aria-label="표시 이름" value={userDisplayName} onChange={(event) => setUserDisplayName(event.currentTarget.value)} />
                    <input aria-label="소속" value={userAffiliation} onChange={(event) => setUserAffiliation(event.currentTarget.value)} />
                    <SelectMenu className="admin-user-select" size="small" value={userRole} options={userRoleOptions} ariaLabel="역할" onChange={(value) => { setUserRole(value as UserRole); setUserChangeArmed(false); }} />
                    <SelectMenu className="admin-user-select" size="small" value={userStatus} options={userStatuses} ariaLabel="상태" onChange={(value) => { setUserStatus(value as UserStatus); setUserChangeArmed(false); }} />
                    <button className={userChangeArmed ? "is-confirm-armed" : ""} type="submit" disabled={saving}>{userChangeArmed ? <AlertTriangle size={14} /> : <Save size={14} />} {userChangeArmed ? "한 번 더 눌러 변경" : "변경"}</button>
                  </form>
                ) : (
                  <div className="admin-row-summary-line">
                    <button className="admin-row-trigger" type="button" aria-expanded={false} onClick={() => chooseUser(user)}>
                      <span className="admin-user-summary"><strong>{user.loginId}</strong><small>{user.displayName || "이름 없음"}</small><small>{user.affiliation || "소속 없음"}</small></span>
                      <span className="admin-row-meta"><i className={`status-dot status-${user.status}`} />{userRoleLabel(user.role)} · {userStatuses.find((item) => item.value === user.status)?.label}<ChevronDown size={15} /></span>
                    </button>
                    {user.status === "invited" && <button className="admin-approve-user" type="button" disabled={saving} onClick={() => void approveUser(user)}>승인</button>}
                  </div>
                )}
                {selectedUser?.id === user.id && (
                  <div className="admin-row-detail">
                    {userChangeArmed && <p className="admin-inline-confirm"><AlertTriangle size={14} /> 역할 또는 상태를 변경하면 기존 세션이 종료될 수 있습니다.</p>}
                    <div className="admin-user-facts"><span>최근 로그인 {formatDate(user.lastLoginAt)}</span><span>실패 {user.failedLoginCount}회</span><span>생성 {formatDate(user.createdAt)}</span></div>
                    <form className="admin-password-reset" onSubmit={(event) => void resetUserPassword(event)}>
                      <KeyRound size={15} />
                      <input aria-label="새 비밀번호" type="password" autoComplete="new-password" placeholder="새 비밀번호" value={resetPassword} onChange={(event) => { setResetPassword(event.currentTarget.value); setPasswordResetArmed(false); }} required />
                      <label><input type="checkbox" checked={mustChangePassword} onChange={(event) => { setMustChangePassword(event.currentTarget.checked); setPasswordResetArmed(false); }} /> 다음 로그인 시 변경</label>
                      <button className={passwordResetArmed ? "is-confirm-armed" : ""} type="submit" disabled={saving || !resetPassword}>{passwordResetArmed ? "한 번 더 눌러 Reset" : "Reset"}</button>
                      {passwordResetArmed && <p className="admin-inline-confirm"><AlertTriangle size={14} /> 비밀번호를 재설정하면 기존 세션이 종료됩니다.</p>}
                    </form>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {tab === "usage" && (
        <section className="admin-section admin-usage" aria-label="사용 통계">
          <div className="admin-usage-heading">
            <div><strong>조직 사용 현황</strong><small>활동 사용자는 해당 날짜에 로그인했거나 Agent Run을 시작한 고유 사용자입니다. · {usageStatistics?.timezone ?? "Asia/Seoul"}</small></div>
            <div className="admin-usage-period"><span>조회 기간</span><SelectMenu className="admin-usage-period-select" size="small" width="auto" align="end" value={String(usagePeriod)} options={usagePeriodOptions} ariaLabel="조회 기간" onChange={(value) => setUsagePeriod(Number(value) as 0 | 30 | 90)} /></div>
          </div>
          {usageStatistics && <>
            <div className="admin-usage-kpis">
              <div><span>DAU</span><strong>{usageStatistics.summary.dau.toLocaleString()}</strong><small>오늘 활동</small></div>
              <div><span>WAU</span><strong>{usageStatistics.summary.wau.toLocaleString()}</strong><small>최근 7일</small></div>
              <div><span>MAU</span><strong>{usageStatistics.summary.mau.toLocaleString()}</strong><small>최근 30일</small></div>
              <div><span>고착도</span><strong>{usageStatistics.summary.stickinessPercent}%</strong><small>DAU / MAU</small></div>
              <div><span>신규 사용자</span><strong>{usageStatistics.summary.newUsers30d.toLocaleString()}</strong><small>최근 30일</small></div>
              <div><span>Agent Run</span><strong>{usageStatistics.summary.runs.toLocaleString()}</strong><small>선택 기간</small></div>
            </div>
            <div className="admin-usage-trend-heading"><div><strong>{usageMetricLabels[usageMetric]} 추이</strong><small>일별 집계</small></div><div role="group" aria-label="차트 지표">{(Object.keys(usageMetricLabels) as UsageMetric[]).map((metric) => <button type="button" aria-pressed={usageMetric === metric} onClick={() => setUsageMetric(metric)} key={metric}>{usageMetricLabels[metric]}</button>)}</div></div>
            <UsageTrendChart statistics={usageStatistics} metric={usageMetric} />
            <div className="admin-usage-table-heading"><div><strong>사용자별 접속 통계</strong><small>{filteredUsageUsers.length}명 · {usagePeriod === 0 ? "전체 기간" : `최근 ${usagePeriod}일`} 기준</small></div></div>
            <div className="admin-usage-table-scroll">
              <div className="admin-usage-table" role="table" aria-label="사용자별 접속 통계">
                <div className="admin-usage-table-row is-header" role="row"><span>ID / 사용자</span><span>최근 로그인</span><span>활동일</span><span>접속</span><span>Run</span><span>입력 토큰</span><span>Cached 입력 토큰</span><span>Hit Ratio</span><span>Output 토큰</span><span>예상 비용</span><span>휴면</span></div>
                {filteredUsageUsers.map((user) => <div className="admin-usage-table-row" role="row" key={user.userId}><span><strong>{user.loginId}</strong><small>{[user.displayName, user.affiliation].filter(Boolean).join(" · ") || "-"}</small></span><time>{formatDate(user.lastLoginAt)}</time><span>{user.activeDays}일</span><span>{user.loginCount}회</span><span>{user.runCount}회</span><span>{user.inputTokens.toLocaleString()}</span><span>{user.cachedInputTokens.toLocaleString()}</span><span>{user.cacheHitRatioPercent.toFixed(1)}%</span><span>{user.outputTokens.toLocaleString()}</span><span>{user.estimatedCostUsd ? `$${user.estimatedCostUsd.toFixed(4)}` : "-"}</span><span>{user.inactiveDays === null ? "기록 없음" : user.inactiveDays === 0 ? "오늘" : `${user.inactiveDays}일`}</span></div>)}
              </div>
            </div>
          </>}
          {!usageStatistics && !loading && !error && <p className="workspace-empty">집계할 사용 기록이 없습니다.</p>}
        </section>
      )}

      {tab === "conversations" && (
        <section className="admin-conversation-layout" aria-label="전체 대화 모니터링 조회">
          <div className="admin-list-panel">
            <div className="admin-conversation-heading">
              <div className="admin-count">대화 {conversations.length} / {conversationTotal}건</div>
              <div className="admin-conversation-controls">
                <div className="admin-control-label"><span>조회 한도</span><SelectMenu className="admin-limit-select" size="small" width="auto" align="end" value={String(conversationLimit)} options={adminListLimitOptions} ariaLabel="대화 조회 한도" onChange={(value) => setConversationLimit(Number(value) as AdminListLimit)} /></div>
                <button className="tooltip-control admin-conversation-export" type="button" aria-label="대화 Excel 내보내기" data-tooltip="Excel 내보내기" disabled={exportingConversations} onClick={() => void exportConversations()}>{exportingConversations ? <LoaderCircle className="is-running" size={14} /> : <Download size={14} />}</button>
                <div className="admin-conversation-view-toggle" role="group" aria-label="대화 목록 보기 방식">
                  <button className="tooltip-control" type="button" aria-label="메시지순" data-tooltip="메시지순" aria-pressed={conversationViewMode === "recent"} onClick={() => setConversationViewMode("recent")}><MessageSquare size={14} /></button>
                  <button className="tooltip-control" type="button" aria-label="사용자별" data-tooltip="사용자별" aria-pressed={conversationViewMode === "user"} onClick={() => setConversationViewMode("user")}><Users size={14} /></button>
                </div>
              </div>
            </div>
            <div className="admin-list">
              {conversationViewMode === "recent" && conversations.map(renderConversationRow)}
              {conversationViewMode === "user" && conversationsByUser.map(([userId, items]) => {
                const expanded = !collapsedConversationUsers.has(userId);
                return (
                  <section className="admin-conversation-user-group" key={userId} aria-label={`${userId} 대화`}>
                    <button className="admin-conversation-user-trigger" type="button" aria-expanded={expanded} onClick={() => setCollapsedConversationUsers((current) => {
                      const next = new Set(current);
                      if (next.has(userId)) next.delete(userId);
                      else next.add(userId);
                      return next;
                    })}>
                      <strong>{userId}</strong><span>{items.length}건</span><ChevronDown size={14} />
                    </button>
                    {expanded && items.map(renderConversationRow)}
                  </section>
                );
              })}
            </div>
          </div>
          <div className="admin-conversation-detail">
            {detailLoading && <p><LoaderCircle className="is-running" size={15} /> 대화를 확인하고 있습니다.</p>}
            {!detailLoading && !selectedConversation && <p className="workspace-empty">대화를 선택하면 읽기 전용 모니터링 상세가 표시됩니다.</p>}
            {selectedConversation && !detailLoading && (
              <>
                <header><div><strong>{selectedConversation.conversation.title}</strong><small>{selectedConversation.conversation.owner.loginId}</small></div></header>
                {selectedConversation.feedback.length > 0 && <section className="admin-feedback-section"><h2>사용자 의견 <span>{selectedConversation.feedback.length}건</span></h2>{selectedConversation.feedback.map((feedback) => <article className={`admin-feedback-row kind-${feedback.kind} ${feedback.value ? `value-${feedback.value}` : ""}`} key={feedback.id}><header><strong>{feedback.kind === "report" ? "개선 의견" : feedback.value === "like" ? "좋아요" : "싫어요"}</strong><span>{feedback.author.loginId} · {formatDate(feedback.createdAt)}</span></header>{feedback.description && <p>{feedback.description}</p>}{feedback.category && <small>{feedback.category}</small>}</article>)}</section>}
                <section><h2>메시지 {selectedConversation.messages.length}</h2>{selectedConversation.messages.map((message) => <div className={`admin-message role-${message.role}`} key={message.id}><strong>{message.role}</strong><p>{message.text}</p><time>{formatDate(message.createdAt)}</time></div>)}</section>
                <section><h2>Run {selectedConversation.runs.length}</h2>{selectedConversation.runs.map((run) => <div className="admin-audit-line" key={run.runId}><PlayCircle size={14} /><span>{run.status}</span><small>{run.execution.providerId} · {run.execution.modelKey} · {formatDate(run.startedAt)}</small></div>)}</section>
                <section><h2>Artifact {selectedConversation.artifacts.length}</h2>{selectedConversation.artifacts.map((artifact) => <div className="admin-audit-line" key={artifact.id}><FileText size={14} /><span>{artifact.displayName}</span><small>{artifact.mimeType} · v{artifact.currentVersion}</small></div>)}</section>
              </>
            )}
          </div>
        </section>
      )}

      {tab === "audit" && (
        <section className="admin-section" aria-label="모니터링 로그">
          {usageStatistics && (
            <section className="admin-cache-monitoring" aria-label="Prefix cache 모니터링">
              <div className="admin-cache-monitoring-heading">
                <div><strong>Prefix cache</strong><small>Provider 모델 호출 기준 · 같은 Run의 첫 호출과 후속 호출을 분리합니다.</small></div>
                <div className="admin-usage-period"><span>조회 기간</span><SelectMenu className="admin-usage-period-select" size="small" width="auto" align="end" value={String(usagePeriod)} options={usagePeriodOptions} ariaLabel="Cache 조회 기간" onChange={(value) => setUsagePeriod(Number(value) as 0 | 30 | 90)} /></div>
              </div>
              <div className="admin-cache-summary">
                <div><span>Run 첫 호출</span><strong>{usageStatistics.cache.firstCall.cacheHitRatioPercent.toFixed(1)}%</strong><small>{usageStatistics.cache.firstCall.modelCalls.toLocaleString()}회 · Cached {usageStatistics.cache.firstCall.cachedInputTokens.toLocaleString()}</small></div>
                <div><span>Run 내부 후속</span><strong>{usageStatistics.cache.subsequentCalls.cacheHitRatioPercent.toFixed(1)}%</strong><small>{usageStatistics.cache.subsequentCalls.modelCalls.toLocaleString()}회 · Cached {usageStatistics.cache.subsequentCalls.cachedInputTokens.toLocaleString()}</small></div>
              </div>
              <div className="admin-cache-digest-table" role="table" aria-label="Prompt cache static digest별 집계">
                <div className="admin-cache-digest-row is-header" role="row"><span>Static digest</span><span>Provider / Model</span><span>호출</span><span>Cache write</span><span>첫 호출</span><span>후속 호출</span></div>
                {usageStatistics.cache.byStaticDigest.map((item) => <div className="admin-cache-digest-row" role="row" key={`${item.providerId}:${item.modelKey}:${item.digest}`}><code className="tooltip-control" data-tooltip={item.digest}>{item.digest === "unknown" ? "unknown" : item.digest.slice(0, 12)}</code><span>{item.providerId} · {item.modelKey}</span><span>{item.modelCalls.toLocaleString()}</span><span>{item.cacheWriteTokens.toLocaleString()}</span><strong>{item.firstCall.cacheHitRatioPercent.toFixed(1)}%</strong><strong>{item.subsequentCalls.cacheHitRatioPercent.toFixed(1)}%</strong></div>)}
                {usageStatistics.cache.byStaticDigest.length === 0 && <p>집계할 모델 호출이 없습니다.</p>}
              </div>
            </section>
          )}
          <AdminTrafficChart refreshKey={refreshKey} />
          <div className="admin-audit-heading">
            <div className="admin-count">최근 모니터링 이벤트 {auditEvents.length} / {auditTotal}건</div>
            <div className="admin-audit-controls">
              <div className="admin-control-label"><span>조회 한도</span><SelectMenu className="admin-limit-select" size="small" width="auto" align="end" value={String(auditLimit)} options={adminListLimitOptions} ariaLabel="모니터링 로그 조회 한도" onChange={(value) => setAuditLimit(Number(value) as AdminListLimit)} /></div>
              <div className="admin-audit-view-toggle" role="group" aria-label="모니터링 로그 보기 방식">
                <button className="tooltip-control" type="button" aria-label="이벤트순" data-tooltip="이벤트순" aria-pressed={auditViewMode === "recent"} onClick={() => setAuditViewMode("recent")}><List size={14} /></button>
                <button className="tooltip-control" type="button" aria-label="사용자 ID별" data-tooltip="사용자 ID별" aria-pressed={auditViewMode === "user"} onClick={() => setAuditViewMode("user")}><Users size={14} /></button>
              </div>
            </div>
          </div>
          <div className="admin-audit-list">
            {auditViewMode === "recent" && auditEvents.map((event) => <article className={event.result === "success" ? undefined : "is-abnormal"} key={event.id}><time>{formatDate(event.createdAt)}</time><strong>{event.actorLoginId ?? event.actorUserId ?? "시스템"}</strong><strong>{event.action}</strong><span>{event.targetType}{event.targetId ? ` · ${event.targetId.slice(0, 8)}` : ""}</span><small>{event.result} · request {event.requestId?.slice(0, 8) ?? "-"}</small></article>)}
            {auditViewMode === "user" && auditEventsByUser.map(([userId, events]) => {
              const expanded = !collapsedAuditUsers.has(userId);
              return (
                <section className="admin-audit-user-group" key={userId} aria-label={`${userId} 모니터링 이벤트`}>
                  <button className="admin-audit-user-trigger" type="button" aria-expanded={expanded} onClick={() => setCollapsedAuditUsers((current) => {
                    const next = new Set(current);
                    if (next.has(userId)) next.delete(userId);
                    else next.add(userId);
                    return next;
                  })}>
                    <strong>{userId}</strong><span>{events.length}건</span><ChevronDown size={14} />
                  </button>
                  {expanded && events.map((event) => <article className={event.result === "success" ? undefined : "is-abnormal"} key={event.id}><time>{formatDate(event.createdAt)}</time><strong>{event.action}</strong><span>{event.targetType}{event.targetId ? ` · ${event.targetId.slice(0, 8)}` : ""}</span><small>{event.result} · request {event.requestId?.slice(0, 8) ?? "-"}</small></article>)}
                </section>
              );
            })}
          </div>
        </section>
      )}
      {tab === "policy" && <OrganizationInstructionsPanel />}
    </main>
  );
}

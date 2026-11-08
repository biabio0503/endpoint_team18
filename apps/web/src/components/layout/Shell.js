import Link from 'next/link';
export function Shell({ children }) {
  return <><header className="service-header"><Link href="/" className="brand">진로 로드맵</Link><span className="service-nav">대학생을 위한 개인화 계획</span><Link href="/" className="home-link">시작 화면</Link></header><main className="service-content">{children}</main></>;
}
export function Stepper({ current, blockForward = false }) {
  const steps = [['기본 정보','/input/basic'],['프로젝트 문서','/input/documents'],['이수 과목','/input/courses'],['분석 내용 확인','/input/review']];
  return <nav className="stepper" aria-label="입력 단계">{steps.map(([label, href], i) => <span className="step-wrap" key={href}>{blockForward && i > current ? <span aria-disabled="true">{i + 1}. {label}</span> : <Link className={i === current ? 'current' : ''} aria-current={i === current ? 'step' : undefined} href={href}>{i + 1}. {label}</Link>}{i < 3 && <span aria-hidden="true">›</span>}</span>)}</nav>;
}
export function Heading({ number, title, description }) { return <><div className="eyebrow">{number} / 06</div><h1 className="page-title">{title}</h1><p className="description">{description}</p></>; }
export function Footer({ previous, next, nextLabel, note }) { return <footer className="footer"><div><Link className="button" href={previous}>이전</Link>{note && <div className="footer-note">{note}</div>}</div>{next && <Link className="button primary" href={next}>{nextLabel}</Link>}</footer>; }

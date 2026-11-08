import Link from 'next/link';
import { Stepper, Heading, Footer } from '../../../components/layout/Shell';
export default function Page() { return <><Stepper current={3}/><Heading number="05" title="분석 내용 확인" description="문서에서 확인한 경험과 추가 질문을 검토하는 단계입니다."/><div className="empty-state"><strong>분석 기능을 준비 중입니다</strong><p>문서 분석과 확인할 내용이 준비되면 이곳에 표시됩니다.</p><button className="primary" disabled>로드맵 생성</button></div><Footer previous="/input/courses"/><div className="result-link"><Link href="/result">결과 화면 살펴보기 →</Link></div></>; }

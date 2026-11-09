import { Stepper, Heading, Footer } from '../../../components/layout/Shell';
import ProjectExperienceReview from '../../../features/roadmap/ProjectExperienceReview';
export default function Page() { return <><Stepper current={3}/><Heading number="05" title="분석 내용 확인" description="문서에서 확인한 경험과 추가 질문을 검토하는 단계입니다."/><ProjectExperienceReview/><Footer previous="/input/courses"/></>; }

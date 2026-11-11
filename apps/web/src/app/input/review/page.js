import { Stepper, Heading, Footer } from '../../../components/layout/Shell';
import ProjectExperienceReview from '../../../features/roadmap/ProjectExperienceReview';
import CourseSelectionSummary from '../../../features/intake/CourseSelectionSummary';
export default function Page() { return <><Stepper current={3}/><Heading number="05" title="분석 내용 확인" description="이수 과목과 문서에서 확인한 경험을 검토하는 단계입니다."/><CourseSelectionSummary/><ProjectExperienceReview/><Footer previous="/input/courses"/></>; }

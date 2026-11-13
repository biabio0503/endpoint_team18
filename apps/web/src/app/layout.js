import './style.css';
import './stepup.css';
import { Shell } from '../components/layout/Shell';
export const metadata = { title: '스텝업 | 나만의 진로 설계', description: '프로젝트 경험과 이수 과목을 연결하는 나만의 진로 로드맵' };
export default function RootLayout({ children }) { return <html lang="ko"><body><Shell>{children}</Shell></body></html>; }

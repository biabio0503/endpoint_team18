import './style.css';
import { Shell } from '../components/layout/Shell';
export const metadata = { title: '진로 로드맵', description: '대학생을 위한 개인화 계획' };
export default function RootLayout({ children }) { return <html lang="ko"><body><Shell>{children}</Shell></body></html>; }

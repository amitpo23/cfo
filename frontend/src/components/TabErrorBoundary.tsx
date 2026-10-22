import { Component, type ErrorInfo, type ReactNode } from 'react';

// One tab that fails to render shows a message in its own place. Without this
// a render error in any tab unmounts the whole page and leaves it blank.
type Props = { tab: string; children: ReactNode };
type State = { failed: boolean };

export default class TabErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`dashboard tab "${this.props.tab}" failed to render`, error, info.componentStack);
  }

  componentDidUpdate(previous: Props) {
    if (previous.tab !== this.props.tab && this.state.failed) this.setState({ failed: false });
  }

  render() {
    if (this.state.failed) {
      return (
        <section role="alert" className="rounded-xl bg-white p-5 text-stone-700 shadow-sm">
          <p>הלשונית הזאת לא הוצגה בגלל שגיאה בנתונים. שאר הדשבורד ממשיך לעבוד.</p>
          <button type="button" className="mt-3 text-sm underline" onClick={() => this.setState({ failed: false })}>
            נסה שוב
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}

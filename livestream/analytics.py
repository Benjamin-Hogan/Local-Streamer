import time


class ImprovedAnalytics:
    def __init__(self):
        self.play_counts = {}
        self.view_durations = {}
        self.peak_viewers = 0
        self.current_viewers = 0
        self.session_start_times = {}

    def start_session(self, session_id):
        self.session_start_times[session_id] = time.time()
        self.current_viewers += 1
        self.peak_viewers = max(self.peak_viewers, self.current_viewers)

    def end_session(self, session_id):
        if session_id in self.session_start_times:
            start_time = self.session_start_times.pop(session_id)
            duration = time.time() - start_time
            current_video = self.current_video['name'] if hasattr(
                self, 'current_video') else 'Unknown'
            self.view_durations[current_video] = self.view_durations.get(
                current_video, 0) + duration
            self.current_viewers -= 1

    def increment_play_count(self, video_name):
        self.play_counts[video_name] = self.play_counts.get(video_name, 0) + 1

    def get_analytics(self):
        return {
            'play_counts': self.play_counts,
            'view_durations': {k: round(v, 2) for k, v in self.view_durations.items()},
            'peak_viewers': self.peak_viewers,
            'current_viewers': self.current_viewers,
        }

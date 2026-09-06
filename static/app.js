const statusText = document.getElementById('camera-status');
const feed = document.getElementById('camera-feed');

async function updateCamera() {
  try {
    const response = await fetch('/api/detect');
    if (!response.ok) throw new Error('Camera status unavailable');
    const data = await response.json();
    statusText.textContent = data.name
      ? `Possible match: ${data.name} (${data.school_id}), MAE ${data.score}. Check before use.`
      : data.message;
    // Connect to the video stream only once frames are available.
    if (data.has_frame && !feed.getAttribute('src')) {
      feed.src = '/video_feed';
      feed.hidden = false;
    } else if (!data.has_frame && feed.getAttribute('src')) {
      feed.removeAttribute('src');
      feed.hidden = true;
    }
  } catch (error) {
    statusText.textContent = 'Connection lost. Check that the app is running.';
  }
  setTimeout(updateCamera, 1000);
}
if (statusText) updateCamera();

for (const form of document.querySelectorAll('.delete-form')) {
  form.addEventListener('submit', event => {
    if (!confirm('Delete this record? Historical loans will be kept.')) event.preventDefault();
  });
}
document.getElementById('go-back')?.addEventListener('click', () => history.back());

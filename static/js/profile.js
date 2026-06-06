document.addEventListener("DOMContentLoaded", () => {
  // --- Profile Dropdown & Image Upload (Global) ---
  const sidebarProfileTrigger = document.getElementById('sidebarProfileTrigger') || document.getElementById('topbarProfileTrigger');
  const profileDropdown = document.getElementById('profileDropdown');

  if (sidebarProfileTrigger && profileDropdown) {
    sidebarProfileTrigger.addEventListener('click', (e) => {
      if (profileDropdown.contains(e.target)) return;
      profileDropdown.classList.toggle('show');
      profileDropdown.style.display = profileDropdown.classList.contains('show') ? 'block' : 'none';
      e.stopPropagation();
    });

    document.addEventListener('click', (e) => {
      if (!sidebarProfileTrigger.contains(e.target)) {
        profileDropdown.classList.remove('show');
        profileDropdown.style.display = 'none';
      }
    });
  }

  const profileImageInput = document.getElementById('profileImageInput');
  const changePictureBtn = document.getElementById('changePictureBtn');
  const removePictureBtn = document.getElementById('removePictureBtn');
  const sidebarAvatarImg = document.getElementById('sidebarAvatarImg') || document.getElementById('globalAvatarImg');
  const sidebarAvatarDiv = document.getElementById('sidebarAvatarDiv') || document.getElementById('globalAvatarDiv');
  // Handle landing page top navbar avatars as well if present
  const topbarAvatarImg = document.getElementById('topbarAvatarImg') || document.querySelector('.navbar .user-avatar-top');
  const topbarAvatarDiv = document.getElementById('topbarAvatarDiv') || document.querySelector('.navbar .user-avatar-top:not(img)');

  function showProfileToast(message, isError = false) {
    let toast = document.querySelector('.profile-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'profile-toast';
      document.body.appendChild(toast);
    }
    toast.className = 'profile-toast' + (isError ? ' error' : '');
    toast.innerHTML = isError ? `<i class="bi bi-exclamation-circle"></i> ${message}` : `<i class="bi bi-check-circle"></i> ${message}`;

    void toast.offsetWidth; // Force reflow
    toast.classList.add('show');

    setTimeout(() => {
      toast.classList.remove('show');
    }, 3000);
  }

  if (changePictureBtn && profileImageInput) {
    changePictureBtn.addEventListener('click', (e) => {
      e.preventDefault();
      profileImageInput.click();
      if (profileDropdown) {
        profileDropdown.classList.remove('show');
        profileDropdown.style.display = 'none';
      }
    });

    profileImageInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('image', file);

      try {
        const res = await fetch('/api/profile/upload-image', {
          method: 'POST',
          body: formData
        });
        const data = await res.json();

        if (data.ok) {
          showProfileToast("Profile picture updated successfully");
          if (sidebarAvatarImg) {
            sidebarAvatarImg.src = data.url;
            sidebarAvatarImg.style.display = 'flex';
          }
          if (sidebarAvatarDiv) sidebarAvatarDiv.style.display = 'none';

          if (topbarAvatarImg) {
            topbarAvatarImg.src = data.url;
            topbarAvatarImg.style.display = 'flex';
          }
          if (topbarAvatarDiv) topbarAvatarDiv.style.display = 'none';
        } else {
          showProfileToast(data.error || "Upload failed", true);
        }
      } catch (err) {
        showProfileToast("An error occurred during upload", true);
      } finally {
        profileImageInput.value = '';
      }
    });
  }

  if (removePictureBtn) {
    removePictureBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      if (profileDropdown) {
        profileDropdown.classList.remove('show');
        profileDropdown.style.display = 'none';
      }
      try {
        const res = await fetch('/api/profile/remove-image', { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
          showProfileToast("Profile picture removed");
          if (sidebarAvatarImg) sidebarAvatarImg.style.display = 'none';
          if (sidebarAvatarDiv) sidebarAvatarDiv.style.display = 'flex';

          if (topbarAvatarImg) topbarAvatarImg.style.display = 'none';
          if (topbarAvatarDiv) topbarAvatarDiv.style.display = 'flex';
        }
      } catch (err) {
        showProfileToast("Failed to remove picture", true);
      }
    });
  }
});

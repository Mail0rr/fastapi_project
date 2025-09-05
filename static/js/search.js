document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('userSearch');
    const searchResults = document.getElementById('searchResults');
    const searchError = document.getElementById('searchError');
    const selectedUserName = document.getElementById('selectedUserName');
    const selectedUserAvatar = document.getElementById('selectedUserAvatar');

    let searchTimeout;

    searchInput.addEventListener('input', function() {
        const query = this.value.trim();

        // Clear previous timeout
        clearTimeout(searchTimeout);

        // Hide previous results and errors
        searchResults.classList.add('hidden');
        searchError.classList.add('hidden');

        if (query.length === 0) {
            return;
        }

        // Debounce search
        searchTimeout = setTimeout(() => {
            searchUser(query);
        }, 500);
    });

    searchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            const query = this.value.trim();
            if (query.length > 0) {
                clearTimeout(searchTimeout);
                searchUser(query);
            }
        }
    });

    async function searchUser(username) {
        try {
            const response = await fetch(`/api/search-user/${encodeURIComponent(username)}`);

            if (response.ok) {
                const user = await response.json();
                displaySearchResult(user);
            } else {
                const error = await response.json();
                showError(error.detail || 'Человека с таким username\'ом не найдено');
            }
        } catch (error) {
            console.error('Search error:', error);
            showError('Произошла ошибка при поиске');
        }
    }

    function displaySearchResult(user) {
        searchError.classList.add('hidden');

        const userInitial = user.nickname ? user.nickname[0].toUpperCase() : user.username[0].toUpperCase();

        searchResults.innerHTML = `
            <div class="px-2 mb-2">
                <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Результаты поиска</h3>
            </div>
            <div class="flex items-center p-3 rounded-lg hover:bg-discord-dark/60 cursor-pointer transition-all duration-200 group user-result"
                 data-username="${user.username}" data-nickname="${user.nickname}">
                <div class="relative">
                    <div class="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center mr-3">
                        <span class="text-white font-semibold text-sm">${userInitial}</span>
                    </div>
                    <div class="absolute -bottom-1 -right-1 w-3 h-3 bg-discord-green border-2 border-discord-darker mr-3 rounded-full"></div>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex justify-between items-center">
                        <span class="font-medium text-gray-200 group-hover:text-white transition-colors">${user.nickname}</span>
                    </div>
                    <p class="text-sm text-gray-400 truncate group-hover:text-gray-300 transition-colors">@${user.username}</p>
                </div>
                <div class="w-2 h-2 bg-discord-blue rounded-full opacity-0 group-hover:opacity-100 transition-opacity"></div>
            </div>
        `;

        searchResults.classList.remove('hidden');

        // Add click handler for the result
        const userResult = searchResults.querySelector('.user-result');
        userResult.addEventListener('click', function() {
            selectUser(user);
        });
    }

    function selectUser(user) {
        // Update header with selected user info
        selectedUserName.textContent = user.nickname;

        const userInitial = user.nickname ? user.nickname[0].toUpperCase() : user.username[0].toUpperCase();
        selectedUserAvatar.innerHTML = `<span class="text-white font-semibold text-xs">${userInitial}</span>`;

        // Clear search
        searchInput.value = '';
        searchResults.classList.add('hidden');
        searchError.classList.add('hidden');

        console.log('[v0] Selected user:', user);
    }

    function showError(message) {
        searchResults.classList.add('hidden');
        searchError.querySelector('p').textContent = message;
        searchError.classList.remove('hidden');
    }
});
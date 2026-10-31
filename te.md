   while (q--) {
        int l, r;
        cin >> l >> r;

        long long total_len = r - l + 2;

        long long c1 = cnt1[r] - (l >= 2 ? cnt1[l - 2] : 0);
        long long c0 = total_len - c1;

        long long ans = (c0 * (c0 - 1)) / 2 + (c1 * (c1 - 1)) / 2;
        cout << ans << "\n";
    }

    return 0;
}
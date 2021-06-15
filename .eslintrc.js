'use strict';

module.exports = {
    env: {
        browser: true,
    },
    parserOptions: {
        sourceType: 'module',
        ecmaVersion: 2015,
    },
    rules: {
        'indent': ['error', 4],
        'capitalized-comments': 'off',
        'indent': 'off', // TODO: turn back on after fixing switch statement indentation
    },
}

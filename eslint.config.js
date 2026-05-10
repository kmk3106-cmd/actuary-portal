export default [
  {
    files: ['**/*.js', '**/*.html'],
    rules: {
      'no-constant-condition': 'error',
      'no-unreachable': 'error',
      'no-undef': 'warn',
      'no-unused-vars': 'warn',
    },
  },
];

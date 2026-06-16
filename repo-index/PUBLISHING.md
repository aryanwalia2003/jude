# Publishing repo-index to PyPI

This guide explains how to publish new versions of `repo-index` to PyPI.

## Prerequisites

- You have admin access to the GitHub repository
- You have [configured PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) (GitHub OIDC)
- You have a PyPI account that is an owner/maintainer of the `repo-index` project

## Steps to Publish

### 1. Update Version

Edit `repo-index/pyproject.toml` and bump the version:

```toml
[project]
version = "0.2.0"  # Update this
```

### 2. Commit and Tag

```bash
git add repo-index/pyproject.toml
git commit -m "bumps repo-index version to 0.2.0"
git tag repo-index-v0.2.0
git push origin main
git push origin repo-index-v0.2.0
```

### 3. Automated Publishing

When you push the tag with format `repo-index-v*`, the GitHub Actions workflow will:

1. Checkout the code
2. Build the sdist and wheel distributions
3. Publish to PyPI using trusted publishing

You can monitor the workflow progress in the **Actions** tab.

## Verifying the Release

After publishing, verify the package:

```bash
# Check on PyPI
pip index versions repo-index

# Install and test
pip install --upgrade repo-index
repo-index --help
```

## Rollback (if needed)

If something goes wrong:

1. Delete the tag locally and remotely:
   ```bash
   git tag -d repo-index-v0.2.0
   git push origin :repo-index-v0.2.0
   ```

2. Fix the issue in code

3. Re-tag and push:
   ```bash
   git tag repo-index-v0.2.0-fixed
   git push origin repo-index-v0.2.0-fixed
   ```

## First-Time Setup (One-time)

If this is the first publish to PyPI:

1. Create the `release` environment in GitHub:
   - Go to repo → Settings → Environments
   - Click "New environment" → name it `release`
   - No required reviewers needed for OIDC

2. Add trusted publisher to PyPI:
   - Go to [PyPI](https://pypi.org) → Account settings → Publishing
   - Add publisher:
     - PyPI Project Name: `repo-index`
     - GitHub Repository Owner: `aryanwalia`
     - Repository Name: `ai-infra`
     - Workflow Name: `publish-repo-index.yml`
     - Environment Name: `release`

3. Test with a pre-release:
   ```bash
   git tag repo-index-v0.1.0rc1
   git push origin repo-index-v0.1.0rc1
   ```

   Then verify at https://pypi.org/project/repo-index/

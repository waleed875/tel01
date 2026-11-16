"""Destructive end-to-end smoke against a disposable local Gitea service.

Only run with a throwaway CI user and database. Requires GITEA_INTERNAL_URL,
GITEA_OWNER and GITEA_API_TOKEN. It never prints the token.
"""
import asyncio
import os
import secrets
from gitea_client import GiteaClient, GiteaError


async def main():
    client = GiteaClient()
    if not client.configured():
        raise SystemExit("Gitea smoke test requires a configured disposable service account")
    name = "smoke-" + secrets.token_hex(8)
    print("Creating isolated private test repository", flush=True)
    created = False
    try:
        repo = await client.create_repo(name, "Disposable integration smoke test")
        created = True
        assert repo["name"] == name
        assert repo["private"] is True, "Test repository must be private"
        archived = await client.set_archived(name, True)
        assert archived["archived"] is True
        unarchived = await client.set_archived(name, False)
        assert unarchived["archived"] is False
        listing = await client.entries(name)
        assert isinstance(listing, list)
        source = "src/demo.py"
        first = await client.write_file(name, source, b"print('first')\n",
                                        sha=None, message="Create smoke file")
        sha1 = first.get("content", {}).get("sha")
        assert sha1 and len(sha1) == 40
        read = await client.read_file(name, source)
        assert read["sha"] == sha1
        assert read["data"] == b"print('first')\n"
        second = await client.write_file(name, source, b"print('changed')\n",
                                         sha=sha1, message="Update smoke file")
        sha2 = second.get("content", {}).get("sha")
        assert sha2 and sha2 != sha1
        conflict = False
        try:
            await client.write_file(name, source, b"print('stale')\n",
                                    sha=sha1, message="Attempt stale edit")
        except GiteaError as exc:
            conflict = exc.status == 409
        assert conflict, "Stale SHA update unexpectedly succeeded"
        data = await client.read_file(name, source)
        assert data["data"] == b"print('changed')\n"
        assert data["sha"] == sha2
        binary = b"\x00\xff\xfe\x10"
        await client.write_file(name, "boards/data.bin", binary, sha=None,
                                message="Upload binary fixture")
        assert (await client.read_file(name, "boards/data.bin"))["data"] == binary
        search_result = await client.search_paths(name, "demo")
        assert any(row["path"] == source for row in search_result["matches"]), "Nested search failed"
        commits = await client.commits(name)
        assert len(commits) >= 3
        # Rename in a single commit, without overwriting an existing destination.
        renamed = "src/renamed.py"
        await client.rename_file(name, source, renamed, sha=sha2,
                                 message="Rename source fixture")
        assert (await client.read_file(name, renamed))["data"] == b"print('changed')\n"
        try:
            await client.read_file(name, source)
        except GiteaError as exc:
            assert exc.status == 404
        else:
            raise AssertionError("Original path remained after atomic rename")
        await client.delete_file(name, renamed, sha2, "Remove source fixture")
        print("PASS: repo visibility, Git commits, edit, stale-SHA conflict, binary and delete", flush=True)
    finally:
        if created:
            await client.delete_repo(name)
            print("Removed disposable test repository", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

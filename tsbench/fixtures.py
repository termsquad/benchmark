"""Seventeen frozen, independently validated Node coding challenges."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .common import BenchmarkError, require_success, run_command

# Tasks and validators are runner-owned, never placed in the writable worktree.
SPECS = [
 ("double","Return twice the numeric argument.","assert.equal(f(4),8);assert.equal(f(-3),-6)"),
 ("sum","Return the sum of all numbers in an array.","assert.equal(f([1,2,3]),6);assert.equal(f([]),0)"),
 ("factorial","Return factorial of a nonnegative integer, including 0.","assert.equal(f(5),120);assert.equal(f(0),1)"),
 ("reverse","Return the input string in reverse character order.","assert.equal(f('abc'),'cba');assert.equal(f(''),'')"),
 ("unique","Return an array of unique values preserving first-seen order.","assert.deepEqual(f([2,1,2,3,1]),[2,1,3])"),
 ("clamp","Clamp a number between inclusive low and high bounds.","assert.equal(f(12,0,10),10);assert.equal(f(-2,0,10),0)"),
 ("palindrome","Return true when the string is an exact palindrome.","assert.equal(f('racecar'),true);assert.equal(f('robot'),false)"),
 ("countVowels","Count English vowels in a string case-insensitively.","assert.equal(f('Hello'),2);assert.equal(f('xyz'),0)"),
 ("average","Return arithmetic mean of an array, or 0 for empty input.","assert.equal(f([2,4,6]),4);assert.equal(f([]),0)"),
 ("range","Return integers from 0 up to but excluding n in an array.","assert.deepEqual(f(4),[0,1,2,3]);assert.deepEqual(f(0),[])"),
 ("chunk","Split an array into consecutive arrays of size n.","assert.deepEqual(f([1,2,3,4,5],2),[[1,2],[3,4],[5]])"),
 ("titleCase","Uppercase the initial letter of every space-delimited word.","assert.equal(f('hello world'),'Hello World')"),
 ("fibonacci","Return the nth Fibonacci number with f(0)=0 and f(1)=1.","assert.equal(f(7),13);assert.equal(f(0),0)"),
 ("max","Return largest number in an array, or null when empty.","assert.equal(f([1,9,3]),9);assert.equal(f([]),null)"),
 ("dedupeSorted","Return a sorted ascending array of distinct numbers.","assert.deepEqual(f([3,1,3,2]),[1,2,3])"),
 ("flatten","Flatten an array of arrays by exactly one level.","assert.deepEqual(f([[1,2],[3],[]]),[1,2,3])"),
 ("slugify","Trim, lowercase, and replace runs of spaces with a hyphen.","assert.equal(f(' Hello   World '),'hello-world');assert.equal(f('A B'),'a-b')")
]


def fixture_digest() -> str:
    return hashlib.sha256(json.dumps(SPECS,separators=(",",":")).encode()).hexdigest()


def task_prompt(task_id: int) -> str:
    name, instructions, _ = SPECS[task_id]
    return ("Implement the exported JavaScript function '"+name+"' in tasks/"+str(task_id).zfill(2)+
            "/solution.js. "+instructions+" Do not alter any other files. "+
            "No third-party dependencies. Finish after implementing the change.")


def create_base(root: Path) -> Path:
    base = root / "fixture-base"
    base.mkdir(parents=True,exist_ok=False)
    for index,(name,_,_) in enumerate(SPECS):
        folder = base / "tasks" / str(index).zfill(2)
        folder.mkdir(parents=True)
        (folder / "solution.js").write_text(
            "module.exports = function "+name+"(...args) { throw Error('not implemented'); };\n")
    (base / "README.md").write_text("TermSquad frozen benchmark fixture. Edit only the assigned solution.\n")
    require_success(run_command(["git","init","-q",str(base)],10),"git init")
    require_success(run_command(["git","-C",str(base),"add","."],10),"git add")
    require_success(run_command(["git","-C",str(base),"-c","user.name=TermSquad Benchmark",
                                 "-c","user.email=benchmark@localhost","commit","-qm","freeze fixture"],10),"git commit")
    return base


def create_worktree(base: Path, root: Path, label: str) -> Path:
    target = root / ("task-" + label)
    require_success(run_command(["git","-C",str(base),"worktree","add","-q","--detach",str(target),"HEAD"],15),"git worktree add")
    return target


def validate_task(task_id: int, worktree: Path, timeout: float = 10.0) -> dict:
    name, _, assertions = SPECS[task_id]
    path = "./tasks/"+str(task_id).zfill(2)+"/solution.js"
    # Test code is sourced from the immutable package, never from agent-editable files.
    script = "const assert=require('node:assert/strict');const f=require("+json.dumps(path)+");"+assertions+";console.log('PASS')"
    try:
        response = run_command(["node","-e",script], timeout, cwd=worktree, max_output=2000)
        return {"passed":response["returncode"]==0 and "PASS" in response["stdout"],
                "elapsed_seconds":response["elapsed_seconds"]}
    except Exception:
        return {"passed":False,"elapsed_seconds":None}

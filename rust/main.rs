use egg::{define_language, rewrite as rw, *};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{self, Read},
    time::Duration,
};

define_language! {
    pub enum Lang {
        "bv" = Bv([Id; 2]), "var" = Var([Id; 2]),
        "add" = Add([Id; 3]), "sub" = Sub([Id; 3]), "mul" = Mul([Id; 3]),
        "and" = And([Id; 3]), "or" = Or([Id; 3]), "xor" = Xor([Id; 3]),
        "shl" = Shl([Id; 3]), "lshr" = Lshr([Id; 3]), "ashr" = Ashr([Id; 3]),
        "eq" = Eq([Id; 3]), "ult" = Ult([Id; 3]), "slt" = Slt([Id; 3]),
        "not" = Not([Id; 2]), "neg" = Neg([Id; 2]),
        "zext" = Zext([Id; 2]), "sext" = Sext([Id; 2]),
        "slice" = Slice([Id; 3]), "concat" = Concat([Id; 3]),
        "mux" = Mux([Id; 4]), "sum" = Sum([Id; 4]), "fma" = Fma([Id; 4]),
        Num(u64), Symbol(Symbol),
    }
}
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Facts {
    width: Option<u32>,
    constant: Option<u64>,
    number: Option<u64>,
}
#[derive(Default, Debug)]
pub struct Bits;
fn mask(w: u32) -> u64 {
    if w == 64 {
        u64::MAX
    } else {
        (1u64 << w) - 1
    }
}
fn signed(v: u64, w: u32) -> i128 {
    if v & (1u64 << (w - 1)) != 0 {
        v as i128 - (1i128 << w)
    } else {
        v as i128
    }
}
fn operands(n: &Lang) -> &[Id] {
    match n {
        Lang::Bv(_) | Lang::Var(_) | Lang::Num(_) | Lang::Symbol(_) => &[],
        Lang::Slice(a) => &a[1..2],
        _ => &n.children()[1..],
    }
}
impl Analysis<Lang> for Bits {
    type Data = Facts;
    fn make(g: &mut EGraph<Lang, Self>, n: &Lang, _: Id) -> Facts {
        if let Lang::Num(v) = n {
            return Facts {
                number: Some(*v),
                ..Facts::default()
            };
        }
        if let Lang::Symbol(_) = n {
            return Facts::default();
        }
        let ids = n.children();
        let w = g[ids[0]].data.number.expect("literal width required");
        assert!((1..=64).contains(&w), "supported widths are 1..64");
        let w = w as u32;
        let mut d = Facts {
            width: Some(w),
            ..Facts::default()
        };
        if let Lang::Bv(a) = n {
            d.constant = Some(g[a[1]].data.number.unwrap() & mask(w));
            return d;
        }
        if let Lang::Var(_) = n {
            return d;
        }
        let args = operands(n);
        let widths: Vec<_> = args
            .iter()
            .map(|i| g[*i].data.width.expect("data operand required"))
            .collect();
        match n {
            Lang::Add(_)
            | Lang::Sub(_)
            | Lang::Mul(_)
            | Lang::And(_)
            | Lang::Or(_)
            | Lang::Xor(_)
            | Lang::Sum(_)
            | Lang::Fma(_)
            | Lang::Neg(_)
            | Lang::Not(_) => assert!(
                widths.iter().all(|x| *x == w),
                "normalize arithmetic operands"
            ),
            Lang::Mux(_) => assert!(widths == [1, w, w], "mux type mismatch"),
            Lang::Eq(_) | Lang::Ult(_) | Lang::Slt(_) => assert!(w == 1 && widths[0] == widths[1]),
            Lang::Shl(_) | Lang::Lshr(_) | Lang::Ashr(_) => assert!(widths[0] == w),
            Lang::Zext(_) | Lang::Sext(_) => assert!(widths[0] <= w),
            Lang::Concat(_) => assert!(widths[0] + widths[1] == w),
            Lang::Slice(a) => assert!(g[a[2]].data.number.unwrap() + w as u64 <= widths[0] as u64),
            _ => (),
        }
        if let Lang::Mux(a) = n {
            if let Some(s) = g[a[1]].data.constant {
                d.constant = g[if s == 0 { a[3] } else { a[2] }].data.constant;
            }
        }
        let Some(v) = args
            .iter()
            .map(|i| g[*i].data.constant)
            .collect::<Option<Vec<_>>>()
        else {
            return d;
        };
        let result = match n {
            Lang::Add(_) => v[0].wrapping_add(v[1]),
            Lang::Sub(_) => v[0].wrapping_sub(v[1]),
            Lang::Mul(_) => v[0].wrapping_mul(v[1]),
            Lang::And(_) => v[0] & v[1],
            Lang::Or(_) => v[0] | v[1],
            Lang::Xor(_) => v[0] ^ v[1],
            Lang::Not(_) => !v[0],
            Lang::Neg(_) => v[0].wrapping_neg(),
            Lang::Shl(_) => {
                if v[1] >= w as u64 {
                    0
                } else {
                    v[0] << v[1]
                }
            }
            Lang::Lshr(_) => {
                if v[1] >= w as u64 {
                    0
                } else {
                    v[0] >> v[1]
                }
            }
            Lang::Ashr(_) => {
                if v[1] >= w as u64 {
                    if signed(v[0], w) < 0 {
                        mask(w)
                    } else {
                        0
                    }
                } else {
                    (signed(v[0], w) >> v[1]) as u64
                }
            }
            Lang::Eq(_) => (v[0] == v[1]) as u64,
            Lang::Ult(_) => (v[0] < v[1]) as u64,
            Lang::Slt(_) => (signed(v[0], widths[0]) < signed(v[1], widths[1])) as u64,
            Lang::Zext(_) => v[0],
            Lang::Sext(_) => signed(v[0], widths[0]) as u64,
            Lang::Slice(a) => v[0] >> g[a[2]].data.number.unwrap(),
            Lang::Concat(_) => (v[0] << widths[1]) | v[1],
            Lang::Mux(_) => {
                if v[0] == 0 {
                    v[2]
                } else {
                    v[1]
                }
            }
            Lang::Sum(_) => v[0].wrapping_add(v[1]).wrapping_add(v[2]),
            Lang::Fma(_) => v[0].wrapping_mul(v[1]).wrapping_add(v[2]),
            _ => unreachable!(),
        };
        d.constant = Some(result & mask(w));
        d
    }
    fn merge(&mut self, to: &mut Facts, from: Facts) -> DidMerge {
        let old = to.clone();
        if let (Some(a), Some(b)) = (to.width, from.width) {
            assert_eq!(a, b, "unsound width union");
        }
        if let (Some(a), Some(b)) = (to.constant, from.constant) {
            assert_eq!(a, b, "unsound constant union");
        }
        to.width = to.width.or(from.width);
        to.constant = to.constant.or(from.constant);
        to.number = to.number.or(from.number);
        DidMerge(*to != old, *to != from)
    }
    fn modify(g: &mut EGraph<Lang, Self>, id: Id) {
        if let (Some(w), Some(v)) = (g[id].data.width, g[id].data.constant) {
            let wi = g.add(Lang::Num(w as u64));
            let vi = g.add(Lang::Num(v));
            let c = g.add(Lang::Bv([wi, vi]));
            g.union_trusted(id, c, "constant-fold");
        }
    }
}
#[derive(Debug)]
struct ExpandConstant;
impl Applier<Lang, Bits> for ExpandConstant {
    fn apply_one(
        &self,
        g: &mut EGraph<Lang, Bits>,
        eclass: Id,
        s: &Subst,
        _: Option<&PatternAst<Lang>>,
        name: Symbol,
    ) -> Vec<Id> {
        let wi = s["?w".parse().unwrap()];
        let x = s["?x".parse().unwrap()];
        let c = g[s["?c".parse().unwrap()]].data.number.unwrap();
        let w = g[wi].data.number.unwrap() as u32;
        if c < 2 || c > mask(w) {
            return vec![];
        }
        let k = 63 - c.leading_zeros();
        let p = 1u64 << k;
        let mut alternatives = Vec::new();
        let shift = |g: &mut EGraph<Lang, Bits>, amount: u32| {
            let v = g.add(Lang::Num(amount as u64));
            let a = g.add(Lang::Bv([wi, v]));
            g.add(Lang::Shl([wi, x, a]))
        };
        let hi = shift(g, k);
        if c == p {
            alternatives.push(hi);
        } else {
            let v = g.add(Lang::Num(c - p));
            let r = g.add(Lang::Bv([wi, v]));
            let product = g.add(Lang::Mul([wi, x, r]));
            alternatives.push(g.add(Lang::Add([wi, hi, product])));
            if k < 63 {
                let hi = shift(g, k + 1);
                let v = g.add(Lang::Num((p << 1) - c));
                let r = g.add(Lang::Bv([wi, v]));
                let product = g.add(Lang::Mul([wi, x, r]));
                alternatives.push(g.add(Lang::Sub([wi, hi, product])));
            }
        }
        alternatives
            .into_iter()
            .filter(|i| g.union_trusted(eclass, *i, name))
            .collect()
    }
}
fn rules(groups: &[String]) -> Vec<Rewrite<Lang, Bits>> {
    let enabled = |s: &str| groups.iter().any(|g| g == s);
    let mut r = Vec::new();
    if enabled("arithmetic") {
        r.extend(vec![
            rw!("add-comm"; "(add ?w ?a ?b)" => "(add ?w ?b ?a)"),
            rw!("mul-comm"; "(mul ?w ?a ?b)" => "(mul ?w ?b ?a)"),
            rw!("add-zero"; "(add ?w ?a (bv ?w 0))" => "?a"),
            rw!("mul-zero"; "(mul ?w ?a (bv ?w 0))" => "(bv ?w 0)"),
            rw!("mul-one"; "(mul ?w ?a (bv ?w 1))" => "?a"),
            rw!("sub-self"; "(sub ?w ?a ?a)" => "(bv ?w 0)"),
            rw!("sub-zero"; "(sub ?w ?a (bv ?w 0))" => "?a"),
            rw!("double-add"; "(add ?w ?a ?a)" => "(shl ?w ?a (bv ?w 1))"),
            rw!("neg-neg"; "(neg ?w (neg ?w ?a))" => "?a"),
        ]);
        r.extend(rw!("add-assoc"; "(add ?w (add ?w ?a ?b) ?c)" <=> "(add ?w ?a (add ?w ?b ?c))"));
        r.extend(rw!("mul-assoc"; "(mul ?w (mul ?w ?a ?b) ?c)" <=> "(mul ?w ?a (mul ?w ?b ?c))"));
        r.extend(rw!("distribute"; "(mul ?w ?a (add ?w ?b ?c))" <=> "(add ?w (mul ?w ?a ?b) (mul ?w ?a ?c))"));
    }
    if enabled("logic") {
        r.extend(vec![
            rw!("mux-same"; "(mux ?w ?s ?a ?a)" => "?a"),
            rw!("mux-true"; "(mux ?w (bv 1 1) ?a ?b)" => "?a"),
            rw!("mux-false"; "(mux ?w (bv 1 0) ?a ?b)" => "?b"),
            rw!("and-self"; "(and ?w ?a ?a)" => "?a"),
            rw!("or-self"; "(or ?w ?a ?a)" => "?a"),
            rw!("xor-self"; "(xor ?w ?a ?a)" => "(bv ?w 0)"),
            rw!("and-zero"; "(and ?w ?a (bv ?w 0))" => "(bv ?w 0)"),
            rw!("or-zero"; "(or ?w ?a (bv ?w 0))" => "?a"),
            rw!("xor-zero"; "(xor ?w ?a (bv ?w 0))" => "?a"),
            rw!("not-not"; "(not ?w (not ?w ?a))" => "?a"),
            rw!("shift-zero"; "(shl ?w ?a (bv ?k 0))" => "?a"),
            rw!("right-shift-zero"; "(lshr ?w ?a (bv ?k 0))" => "?a"),
        ]);
    }
    if enabled("exchange") {
        r.extend(rw!("mux-add"; "(mux ?w ?s (add ?w ?a ?b) (add ?w ?a ?c))" <=> "(add ?w ?a (mux ?w ?s ?b ?c))"));
        r.extend(rw!("mux-mul"; "(mux ?w ?s (mul ?w ?a ?b) (mul ?w ?a ?c))" <=> "(mul ?w ?a (mux ?w ?s ?b ?c))"));
        r.extend(rw!("factor-shift-add"; "(add ?w (shl ?w ?a ?s) (shl ?w ?b ?s))" <=> "(shl ?w (add ?w ?a ?b) ?s)"));
        r.extend(
            rw!("move-shift-mul"; "(mul ?w (shl ?w ?a ?s) ?b)" <=> "(shl ?w (mul ?w ?a ?b) ?s)"),
        );
    }
    if enabled("merge") {
        r.extend(rw!("merge-sum"; "(add ?w (add ?w ?a ?b) ?c)" <=> "(sum ?w ?a ?b ?c)"));
        r.extend(rw!("merge-fma"; "(add ?w (mul ?w ?a ?b) ?c)" <=> "(fma ?w ?a ?b ?c)"));
    }
    if enabled("constants") {
        r.push(
            Rewrite::new(
                "constant-expand",
                "(mul ?w ?x (bv ?w ?c))".parse::<Pattern<Lang>>().unwrap(),
                ExpandConstant,
            )
            .unwrap(),
        );
    }
    r
}
fn op_name(n: &Lang) -> &'static str {
    match n {
        Lang::Bv(_) => "const",
        Lang::Var(_) => "var",
        Lang::Add(_) => "add",
        Lang::Sub(_) => "sub",
        Lang::Mul(_) => "mul",
        Lang::And(_) => "and",
        Lang::Or(_) => "or",
        Lang::Xor(_) => "xor",
        Lang::Shl(_) => "shl",
        Lang::Lshr(_) => "lshr",
        Lang::Ashr(_) => "ashr",
        Lang::Eq(_) => "eq",
        Lang::Ult(_) => "ult",
        Lang::Slt(_) => "slt",
        Lang::Not(_) => "not",
        Lang::Neg(_) => "neg",
        Lang::Zext(_) => "zext",
        Lang::Sext(_) => "sext",
        Lang::Slice(_) => "slice",
        Lang::Concat(_) => "concat",
        Lang::Mux(_) => "mux",
        Lang::Sum(_) => "sum",
        Lang::Fma(_) => "fma",
        _ => "metadata",
    }
}
#[derive(Deserialize)]
struct Request {
    outputs: BTreeMap<String, String>,
    #[serde(default)]
    groups: Option<Vec<String>>,
    #[serde(default = "default_iterations")]
    iterations: usize,
    #[serde(default = "default_nodes")]
    node_limit: usize,
    #[serde(default = "default_seconds")]
    seconds: u64,
    #[serde(default)]
    explain: Option<BTreeMap<String, String>>,
}
fn default_iterations() -> usize {
    8
}
fn default_nodes() -> usize {
    20000
}
fn default_seconds() -> u64 {
    10
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut text = String::new();
    io::stdin().read_to_string(&mut text)?;
    let req: Request = serde_json::from_str(&text)?;
    let groups = req.groups.unwrap_or_else(|| {
        ["arithmetic", "logic", "exchange", "merge", "constants"]
            .map(str::to_string)
            .to_vec()
    });
    for group in &groups {
        if !["arithmetic", "logic", "exchange", "merge", "constants"].contains(&group.as_str()) {
            return Err(format!("unknown rule group {group}").into());
        }
    }
    let mut runner = Runner::<Lang, Bits>::default()
        .with_explanations_enabled()
        .with_iter_limit(req.iterations)
        .with_node_limit(req.node_limit)
        .with_time_limit(Duration::from_secs(req.seconds));
    let exprs: Vec<RecExpr<Lang>> = req
        .outputs
        .values()
        .map(|s| s.parse())
        .collect::<Result<_, _>>()?;
    for e in &exprs {
        runner = runner.with_expr(e);
    }
    let rs = rules(&groups);
    let rule_names: Vec<_> = rs.iter().map(|r| r.name.to_string()).collect();
    let initial_nodes = runner.egraph.total_size();
    runner = runner.run(&rs);
    let roots: BTreeMap<_, _> = req
        .outputs
        .keys()
        .zip(&runner.roots)
        .map(|(s, id)| (s.clone(), usize::from(runner.egraph.find(*id))))
        .collect();
    let g = &runner.egraph;
    let mut classes = Vec::new();
    let mut next_node = 0;
    let mut sorted: Vec<_> = g.classes().filter(|c| c.data.width.is_some()).collect();
    sorted.sort_by_key(|c| c.id);
    for c in sorted {
        let mut nodes = Vec::new();
        for n in &c.nodes {
            let mut node = json!({"id": next_node, "op": op_name(n), "width": c.data.width.unwrap(),
                "args": operands(n).iter().map(|id| usize::from(g.find(*id))).collect::<Vec<_>>()});
            match n {
                Lang::Bv(a) => {
                    node["value"] =
                        json!(g[a[1]].data.number.unwrap() & mask(c.data.width.unwrap()))
                }
                Lang::Var(a) => {
                    let name = g[a[1]]
                        .nodes
                        .iter()
                        .find_map(|n| {
                            if let Lang::Symbol(s) = n {
                                Some(s.to_string())
                            } else {
                                None
                            }
                        })
                        .unwrap();
                    node["name"] = json!(name);
                }
                Lang::Slice(a) => node["offset"] = json!(g[a[2]].data.number.unwrap()),
                _ => (),
            }
            nodes.push(node);
            next_node += 1;
        }
        classes.push(json!({"id": usize::from(c.id), "width": c.data.width, "constant": c.data.constant, "nodes": nodes}));
    }
    let mut explanations: BTreeMap<String, Value> = BTreeMap::new();
    if let Some(targets) = req.explain {
        for ((name, original), expr) in req.outputs.iter().zip(&exprs) {
            if let Some(target) = targets.get(name) {
                let t: RecExpr<Lang> = target.parse()?;
                let a = runner.egraph.lookup_expr(expr).ok_or("original missing")?;
                let b = runner
                    .egraph
                    .lookup_expr(&t)
                    .ok_or("target absent from explored egraph")?;
                if runner.egraph.find(a) != runner.egraph.find(b) {
                    return Err("explanation target not equivalent".into());
                }
                explanations.insert(name.clone(), json!({"original": original, "target": target, "egg_proof": runner.egraph.explain_equivalence(expr, &t).get_flat_string()}));
            }
        }
    }
    println!(
        "{}",
        json!({"classes": classes, "roots": roots, "rule_names": rule_names,
        "stats": {"initial_nodes": initial_nodes, "nodes": next_node, "classes": classes.len(),
                  "iterations": runner.iterations.len(), "stop_reason": format!("{:?}", runner.stop_reason)}, "explanations": explanations})
    );
    Ok(())
}

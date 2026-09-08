use frontage_vm::dict::PyDict;
use frontage_vm::object::*;
#[test]
fn print_sizes() {
    println!("Obj={} Class={} Exc={} Func={} Instance={} PyDict={} Iter={} Module={} Generator={}", core::mem::size_of::<Obj>(), core::mem::size_of::<Class>(), core::mem::size_of::<Exc>(), core::mem::size_of::<Func>(), core::mem::size_of::<Instance>(), core::mem::size_of::<PyDict>(), core::mem::size_of::<Iter>(), core::mem::size_of::<Module>(), core::mem::size_of::<Generator>());
}

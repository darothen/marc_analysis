import os
from itertools import product
from functools import reduce
from subprocess import call

from . utilities import _GIT_COMMIT, remove_intermediates, arg_in_list, cdo_func

__all__ = ['extract_variable', ]

SAVE_VARS = ",time_bnds,hyam,hybm,PS,P0,gw"

def extract_variable(exp, var, out_suffix="", save_dir='',
                     years_omit=5, years_offset=0, re_extract=False):
    """ Extract a timeseries of data for one variable from the raw CESM/MARC output. 

    A few features bear some explanation:

    1) `years_offset` allows you to add a certain number of years to the time
       variable definition. By default, most simulations I do just start in year
       0001. However, this breaks some calendar-anaylsis routines, since the
       standard/Gregorian calendars are not defined prior to the 1500's. It's much
       easier to simply offset the years to the present day and take advantage
       of the analysis tools machinery than it would be to re-write parts of their
       functionality.

    2) By default, the first 5 years of the simulation data will be omitted.

    Parameters
    ----------
    exp : experiment.Experiment
        The container of the experiment information
    var : (var_data.Var or subtype) or str
        The container for the variable info being extracted or just the
        name of a default CESM var
    out_suffix : string
        Suffix for final filename
    save_dir : string
        Path to save directory; defaults to case WORK_DIR.
    years_omit : int
        The number of years to omit from the beginning of the dataset
    years_offset : int
        The number of years to add to the time unit definition.
    re_extract : bool
        Force extraction even if files already exist

    """

    if isinstance(var, str):
        from .var_data import CESMVar
        var = CESMVar(var, )

    if not save_dir:
        save_dir = exp.work_dir

    print() 
    print("---------------------------------")
    print("Processing %s from CESM output" %  var.oldvar)
    print("   experiment: %s" % exp.name)
    print("   for cases:")
    for case, case_vals in exp.case_data.items():
        print("      %s - %r" % (case, case_vals))

    if hasattr(var, 'lev_bnds'): 
        print("   for levels %r" % var.lev_bnds)
    if hasattr(var, 'cdo_method'):
        print("   applying methods %r" % var.cdo_method)
    else:
        print("   No cdo method applied")

    intermediates = []

    ## Combine existing variables, if ncessary
    combine = isinstance(var.oldvar, (list, tuple))
    if combine:
        comb_vars = var.oldvar[:]
        assert var.varname # make sure it was provided!
        print("   will combine %r to compute %s" % (comb_vars, var.varname))
        print("   using %s" % var.ncap_str if var.ncap_str else "simple addition")
        oldvar_extr = ",".join(comb_vars)
    else:
        oldvar_extr = var.oldvar
        if not var.varname: var.varname = var.oldvar

    for i, case_bits in enumerate(exp.all_cases):
        print()
        print("   %02d) [%s]" % (i+1, ', '.join(case_bits)))

        retained_files = []
    
        # fn_extr :-> monthly file with variable subset
        # TODO: `case_bits` should actually be a data structure which tracks what the naming case is so it can be extracted for odd directory paths. Right now we assume the tailing bit is the file identifier.
        case_fn_comb = "_".join(case_bits)
        naming_case_bit = case_bits[-1]
        fn_extr = "%s_%s_monthly.nc" % (case_fn_comb, var.varname)
        in_file = os.path.join(exp.case_path(*case_bits),
                              "%s.cam2.h0.00[0,1][0,%d-9]-*.nc" % (naming_case_bit,
                                                                   years_omit+1, ))
        out_file = os.path.join(save_dir, fn_extr)

        # fn_final :-> the end result of this output
        fn_final = "%s_%s" % (case_fn_comb, var.varname)
        if out_suffix: 
            fn_final += "_%s" % out_suffix
        fn_final += ".nc"
        out_file_final = os.path.join(save_dir, fn_final)

        retained_files.append(out_file)

        if ( re_extract or not os.path.exists(out_file_final) ): 
            print("      Extracting from original dataset")

            # These are important metadata vars (vertical coord system,
            # time, etc) which we will always want to save

            if not hasattr(var, 'lev_bnds'):
                call("ncrcat -O -v %s %s %s" % 
                         (oldvar_extr+SAVE_VARS, in_file, out_file),
                     shell=True)
            else: 
                if len(var.lev_bnds) == 2: lo, hi = var.lev_bnds
                else: lo, hi = var.lev_bnds[0], var.lev_bnds[0]
                call("ncrcat -O -d lev,%d,%d -v %s %s %s" % 
                      (lo, hi, oldvar_extr+SAVE_VARS, in_file, out_file),
                     shell=True)

            if combine:
                print("      combining vars")
                ncap2_args = ["ncap2", "-O", "-s", 
                              "%s=%s" % (var.varname, "+".join(comb_vars)), 
                              out_file, "-o", out_file]
                if var.ncap_str: ncap2_args[3] = "'%s'" % var.ncap_str
                #print ncap2_args
                call(" ".join(ncap2_args), shell=True)

            if hasattr(var, 'cdo_method'):
                if out_suffix: # override if its provided
                    cdo_bit = out_suffix
                else:
                    cdo_bit = "_".join(cdo_arg for cdo_arg in var.cdo_method)

                fn_cdo = "%s_%s_%s.nc" % (case_fn_comb, var.varname, cdo_bit)
                cdo_out_file = os.path.join(save_dir, fn_cdo)

                cdo_func(var.cdo_method, out_file, cdo_out_file)

                out_file = cdo_out_file

                retained_files.append(out_file)

            if (var.varname and (not var.name_change) and not combine):
                for of in retained_files:
                    call(['ncrename', '-v', ".%s,%s" % (var.oldvar, var.varname), of])

            ## Add attributes to variable and global info
            att_list = [ 
                "-a", "years_omit,global,o,i,%d" % (int(years_omit), ), 
                "-a", "years_offset,global,o,i,%d" % (int(years_offset), ), 
                "-a", "git_commit,global,o,c,%s" % _GIT_COMMIT,
            ]
            if hasattr(var, 'attributes'):
                print("      modifying var attributes")
                for att, val in var.attributes.items():
                    dtype = { int: 'i', 
                              str: 'c',
                              float: 'f', }[type(val)]
                    print("         %s: %s (%s)" % (att, val, dtype))

                    att_list.extend(["-a", "%s,%s,o,%s,%s" % \
                                     (att, var.varname, dtype, val)])
                if years_offset > 0:
                    print("         adding time offset")
                    att_list.extend(["-a", 'units,time,o,c,days since %04d-01-01 00:00:00' %
                                           years_offset])
            if att_list:
                for of in retained_files:
                    call(["ncatted", "-O", ] + att_list + [of, ])

            remove_intermediates(intermediates)

            call(['mv', out_file, out_file_final])
            print("      ...done -> %s" % out_file_final)

        else:
            print("      Extracted dataset already present.")
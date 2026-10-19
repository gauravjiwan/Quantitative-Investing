"""Explicit conversion of observation-month labels to information dates."""
import pandas as pd


def formation_year_at_origin(month):
    t=pd.Timestamp(month)
    return t.year-int(t.month<6)


def assert_month_end_information(observation_month,information_date):
    month=pd.Timestamp(observation_month)
    end=month+pd.offsets.MonthEnd(0)
    if pd.Timestamp(information_date)>end:raise ValueError('Future information at forecast origin')
    return end

/*
  Review-only migration for SQL Server.
  Do not run until the target database, mart schema, and deployment permissions
  have been reviewed and approved. This script is not called by the application.
*/

IF SCHEMA_ID(N'mart') IS NULL
BEGIN
    THROW 51000, 'Required schema mart does not exist; review the target database before applying this migration.', 1;
END;
GO

IF OBJECT_ID(N'mart.financial_forecasts', N'U') IS NOT NULL
BEGIN
    THROW 51001, 'mart.financial_forecasts already exists; inspect it before applying this migration.', 1;
END;
GO

CREATE TABLE mart.financial_forecasts
(
    forecast_id UNIQUEIDENTIFIER NOT NULL,
    metric NVARCHAR(64) NOT NULL,
    currency CHAR(3) NOT NULL,
    target_period DATE NOT NULL,
    time_grain NVARCHAR(16) NOT NULL,
    unit NVARCHAR(64) NOT NULL,
    forecast_value DECIMAL(38, 10) NOT NULL,
    forecast_method NVARCHAR(128) NOT NULL,
    lookback_months INT NOT NULL,
    historical_cutoff DATE NOT NULL,
    source_periods_json NVARCHAR(MAX) NOT NULL,
    source_values_json NVARCHAR(MAX) NOT NULL,
    model_version NVARCHAR(64) NOT NULL,
    metric_definition_version NVARCHAR(64) NOT NULL,
    status NVARCHAR(24) NOT NULL,
    provenance_json NVARCHAR(MAX) NOT NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_financial_forecasts_created_at DEFAULT SYSUTCDATETIME(),

    CONSTRAINT PK_financial_forecasts PRIMARY KEY CLUSTERED (forecast_id),
    CONSTRAINT CK_financial_forecasts_monthly CHECK (time_grain = N'monthly'),
    CONSTRAINT CK_financial_forecasts_target_month CHECK (DAY(target_period) = 1),
    CONSTRAINT CK_financial_forecasts_lookback CHECK (lookback_months BETWEEN 1 AND 24),
    CONSTRAINT CK_financial_forecasts_status CHECK (status = N'saved'),
    CONSTRAINT CK_financial_forecasts_source_periods_json CHECK (ISJSON(source_periods_json) = 1),
    CONSTRAINT CK_financial_forecasts_source_values_json CHECK (ISJSON(source_values_json) = 1),
    CONSTRAINT CK_financial_forecasts_provenance_json CHECK (ISJSON(provenance_json) = 1)
);
GO

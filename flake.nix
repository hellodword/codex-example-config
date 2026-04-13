{
  description = "Update config.toml from the OpenAI Codex config sample";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      forAllSystems = f:
        builtins.listToAttrs (map (system: {
          name = system;
          value = f system;
        }) systems);
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          update-config = pkgs.writeShellApplication {
            name = "update-config";
            runtimeInputs = with pkgs; [
              bash
              coreutils
              curl
              gnugrep
              htmlq
            ];
            text = ''
              exec bash ${./scripts/update-config.sh} "$@"
            '';
          };
        in
        {
          default = update-config;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/update-config";
        };
      });
    };
}

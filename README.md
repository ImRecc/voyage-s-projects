# voyage-s-projects
用来放一些小工具
#### ue_blueprint_parser_v2.py, UE5 blueprint nodes to LLMs friendly form
可以直接复制节点然后运行然后让ai哥以少量tokens消耗的条件来理解你(们)干了什么, 如:\
```
EXECUTION PATHS
---------------
Path 1:
  EventActivateAbility(input:-; output:then->CastToCharacter) -> CastToCharacter(input:Object=GetAvatarActorFromActorInfo.ReturnValue; output:AsCharacter->Set As Character.As Character, then->Set As Character) -> Set As Character(input:As Character=CastToCharacter.AsCharacter; output:then->CommitAbility) -> CommitAbility(input:-; output:ReturnValue->Branch.Condition, then->Branch) -> Branch(input:Condition=CommitAbility.ReturnValue; output:then->LaunchCharacter, else->EndAbility) -> LaunchCharacter(input:LaunchVelocity=0.000000,0.000000,650.000000, LaunchVelocity_X=0.0, LaunchVelocity_Y=0.0, LaunchVelocity_Z=GetFloatAttributeFromAbilitySystemComponent.ReturnValue, bXYOverride=false, bZOverride=true; output:then->LatentAbilityCall) -> LatentAbilityCall(input:EventTag=(TagName="State.Movement.Landed"), OnlyTriggerOnce=false, OnlyMatchExact=true; output:EventReceived->BP_ApplyGameplayEffectToSelf) -> BP_ApplyGameplayEffectToSelf(input:Level=0.0; output:then->EndAbility) -> EndAbility(input:-; output:-)

Path 2:
  EventActivateAbility(input:-; output:then->CastToCharacter) -> CastToCharacter(input:Object=GetAvatarActorFromActorInfo.ReturnValue; output:AsCharacter->Set As Character.As Character, then->Set As Character) -> Set As Character(input:As Character=CastToCharacter.AsCharacter; output:then->CommitAbility) -> CommitAbility(input:-; output:ReturnValue->Branch.Condition, then->Branch) -> Branch(input:Condition=CommitAbility.ReturnValue; output:then->LaunchCharacter, else->EndAbility) -> EndAbility(input:-; output:-)


SUPPORTING NODES (data-only / not on an execution path)
-----------------------------------------------------
GetAvatarActorFromActorInfo(input:-; output:ReturnValue->CastToCharacter.Object)
GetAbilitySystemComponentFromActorInfo(input:-; output:ReturnValue->GetFloatAttributeFromAbilitySystemComponent.AbilitySystem)
GetFloatAttributeFromAbilitySystemComponent(input:AbilitySystem=GetAbilitySystemComponentFromActorInfo.ReturnValue, Attribute=(AttributeName="JumpPower",Attribute=/Script/GAS.DoomAttributeSet:JumpPower,AttributeOwner="/Script/CoreUObject.Class\'/Script/GAS.DoomAttributeSet\'"); output:ReturnValue->LaunchCharacter.LaunchVelocity_Z)
Get As Character(input:-; output:As Character->LaunchCharacter.self)
Get As Character(input:-; output:As Character->GetAbilitySystemComponent.Actor)
GetAbilitySystemComponent(input:Actor=Get As Character.As Character; output:ReturnValue->BP_ApplyGameplayEffectToSelf.self)
EdGraphNode_Comment(input:-; output:-)
```
